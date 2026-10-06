"""Original starter recovery with explicit, offline correction/response evidence."""

from copy import deepcopy
from dataclasses import dataclass
import hashlib

import requests

from pbpstats.resources.enhanced_pbp.stats_nba.start_of_period import StatsStartOfPeriod

from .decoder import V3DecodeError


class V3EvidenceRequired(V3DecodeError):
    """Evidence the original would have requested over the network.

    Carries the exact request so a caller can record that response and pass it
    back as V3StarterBoxscore; the adapter itself never makes the request.
    """

    def __init__(self, message, *, period, url, params):
        super().__init__(message)
        self.period, self.url, self.params = period, url, deepcopy(params)


@dataclass(frozen=True)
class V3StarterBoxscore:
    """Recorded response for one exact original period-start boxscore request.

    The caller supplies the original request parameters and response bytes,
    including HTTP status/reason for a failed request. Selection still runs
    through the shared original implementation; this object performs no I/O.
    """

    source_bytes: bytes
    source: str
    pbp_sha256: str
    request_params: dict
    status_code: int = 200
    reason: str = "OK"

    def validate(self, source_bytes, game_id):
        if not isinstance(self.source, str) or not self.source.strip():
            raise V3DecodeError("Starter boxscore evidence requires source provenance")
        if hashlib.sha256(source_bytes).hexdigest() != self.pbp_sha256:
            raise V3DecodeError(
                "Starter boxscore evidence does not match the raw PBP hash"
            )
        if not isinstance(self.source_bytes, bytes):
            raise V3DecodeError(
                "Starter boxscore evidence must be recorded response bytes"
            )
        if not isinstance(self.request_params, dict) or set(self.request_params) != {
            "GameId",
            "StartPeriod",
            "EndPeriod",
            "RangeType",
            "StartRange",
            "EndRange",
        }:
            raise V3DecodeError("Invalid starter boxscore request parameters")
        if self.request_params["GameId"] != game_id or any(
            type(value) is not int or value < 0
            for key, value in self.request_params.items()
            if key != "GameId"
        ):
            raise V3DecodeError("Invalid starter boxscore request identity or interval")
        if (
            type(self.status_code) is not int
            or not 100 <= self.status_code <= 599
            or not isinstance(self.reason, str)
        ):
            raise V3DecodeError("Invalid recorded starter boxscore response status")

    def response_for(self, start):
        url, params = start._get_starter_boxscore_request()
        if self.request_params != params:
            raise V3DecodeError(
                "Starter boxscore evidence does not match the requested interval for period {}".format(
                    start.period
                )
            )
        response = requests.Response()
        response.status_code = self.status_code
        response.reason = self.reason
        response._content = self.source_bytes
        response.request = requests.Request("GET", url, params=params).prepare()
        response.url = response.request.url
        return response


class StarterRecovery:
    """Supply the two I/O boundaries used by original get_period_starters.

    Actual enhanced events retain their original classes and methods. The
    original try/infer/override/fallback dispatcher is invoked on this helper;
    inference and boxscore selection execute on the original start event.
    """

    def __init__(self, start, overrides, boxscores, diagnostics):
        self.start = start
        self.overrides = overrides
        self.boxscores = boxscores
        self.diagnostics = diagnostics
        self.method = "period_events"
        self.applied_teams = []

    def load(self):
        starters = StatsStartOfPeriod.get_period_starters(self)
        self.diagnostics.append(
            dict(
                code="starter_recovery",
                period=self.start.period,
                method=self.method,
                override_teams=self.applied_teams,
                starters=deepcopy(starters),
            )
        )
        return starters

    def _get_period_starters_from_period_events(self, file_directory):
        start = self.start
        starters = start._get_period_starters_from_period_events(
            None, ignore_missing_starters=True
        )
        corrections = self.overrides.get(start.game_id, {}).get(start.period, {})
        # Preserve the original rule: only a team with a non-five inferred set
        # consults the override. A later failure sends the whole period to the
        # boxscore fallback, including any team already corrected here.
        for team, players in starters.items():
            if len(players) != 5:
                if team in corrections:
                    starters[team] = deepcopy(corrections[team])
                    self.applied_teams.append(team)
                    self.method = "period_events_and_overrides"
                else:
                    start._check_both_teams_have_5_starters({team: players}, None)
        return starters

    def _get_starters_from_boxscore_request(self):
        start = self.start
        evidence = self.boxscores.get(start.period)
        if evidence is None:
            url, params = start._get_starter_boxscore_request()
            raise V3EvidenceRequired(
                "Original starter recovery requires recorded boxscore evidence for period {}".format(
                    start.period
                ),
                period=start.period,
                url=url,
                params=params,
            )
        response = evidence.response_for(start)
        self.diagnostics.append(
            dict(
                code="recorded_starter_boxscore",
                period=start.period,
                source=evidence.source,
                sha256=hashlib.sha256(evidence.source_bytes).hexdigest(),
                pbp_sha256=evidence.pbp_sha256,
                request_params=deepcopy(evidence.request_params),
                status_code=evidence.status_code,
            )
        )
        self.method = "boxscore"
        return start._get_starters_from_boxscore_http_response(response)
