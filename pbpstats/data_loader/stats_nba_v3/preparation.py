"""Prepare auditable lineup evidence; unresolved choices require explicit review."""

import hashlib
import re
from collections import defaultdict
from dataclasses import asdict
from decimal import Context, Decimal, localcontext
from pathlib import Path
from types import MappingProxyType

from pbpstats.data_loader.stats_nba_v3.bundle import _json_bytes, _text
from pbpstats.data_loader.stats_nba_v3.game import (
    V3Diagnostic,
    _file,
    _load_inputs,
    _path,
    _stage,
)
from pbpstats.data_loader.stats_nba_v3.lineups import (
    StatsNbaV3LineupLoader,
    V3LineupEvidence,
    lineup_fingerprints,
)
from pbpstats.data_loader.stats_nba_v3.possessions import StatsNbaV3PossessionLoader
from pbpstats.resources.json_copy import json_copy


class V3Preparation:
    """A reviewable candidate and explicit blockers, with no implicit writes."""

    def __init__(self, candidate, template, diagnostics, inputs):
        self._candidate, self._template = json_copy(candidate), json_copy(template)
        self._diagnostics = tuple(diagnostics)
        self._inputs = MappingProxyType(dict(inputs))

    @property
    def diagnostics(self):
        return self._diagnostics

    @property
    def inputs(self):
        return self._inputs

    @property
    def ready(self):
        return not self.diagnostics

    @property
    def lineup_candidate(self):
        return json_copy(self._candidate)

    @property
    def review_template(self):
        return json_copy(self._template)

    @property
    def report(self):
        return dict(
            ready=self.ready,
            diagnostics=[asdict(d) for d in self.diagnostics],
            inputs={k: asdict(v) for k, v in self.inputs.items()},
            lineup_candidate=self.lineup_candidate,
            review_template=self.review_template,
        )

    def write_report(self, path):
        with Path(path).open("xb") as stream:
            stream.write(_json_bytes(self.report))

    def write_review_template(self, path):
        with Path(path).open("xb") as stream:
            stream.write(_json_bytes(self.review_template))

    def write_lineups(self, path):
        """Publish only a validated candidate, to a new file, from unchanged inputs."""
        if not self.ready:
            raise ValueError(
                "preparation has unresolved evidence; inspect diagnostics and review_template"
            )
        for source in self.inputs.values():
            if (
                hashlib.sha256(Path(source.path).read_bytes()).hexdigest()
                != source.sha256
            ):
                raise ValueError(f"preparation input changed: {source.path}")
        with Path(path).open("xb") as stream:
            stream.write(_json_bytes(self.lineup_candidate))


def _reviews(game_id, directory, review, fingerprints):
    if review is None:
        return {}, None
    evidence = (
        review
        if isinstance(review, V3LineupEvidence)
        else V3LineupEvidence.from_file(_path(directory, review))
    )
    data = evidence.data
    if (
        type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
        or data.get("game_id") != game_id
    ):
        raise ValueError("review requires schema_version=1 and matching game_id")
    if any(data.get(k) != v for k, v in fingerprints.items()):
        raise ValueError(
            "review fingerprints do not match current inputs; review the new snapshot"
        )
    for field in ("periods", "batches", "resolved_replays"):
        if not isinstance(data.get(field, []), list) or any(
            not isinstance(r, dict) for r in data.get(field, [])
        ):
            raise ValueError(f"review {field} must be an array of objects")
        for record in data.get(field, []):
            _text(record.get("source"), f"review {field}")
    return data, evidence


def _witnesses(events):
    found, entered = {}, set()
    for event in events:
        if event.kind in (
            "period_start",
            "period_end",
            "timeout",
            "replay",
            "ejection",
        ):
            continue
        if (
            event.kind == "foul"
            and event.subtype in ("Technical", "Hanging Technical")
            or event.free_throw
            and event.free_throw.category == "technical"
        ):
            continue
        for role, participant in event.participants.participants.items():
            pid = participant.player_id
            if pid is None or role == "incoming" or pid in entered or pid in found:
                continue
            found[pid] = dict(
                player_id=pid,
                team_id=participant.team_id,
                source_index=event.group.primary.order,
                role=role,
            )
        if event.kind == "substitution":
            entered.add(event.participants.require_player("incoming"))
    return found


def _starters(events, box, reviews, source, diagnostics):
    ctx = events.context
    by_period = defaultdict(list)
    for event in events.items:
        by_period[event.group.primary.period].append(event)
    manual = {}
    for record in reviews.get("periods", []):
        p = record.get("period")
        if type(p) is not int or p not in by_period or p in manual:
            raise ValueError("duplicate or extraneous reviewed starter period")
        manual[p] = record
    result, pending = [], []
    teams = box.source_data["boxScoreTraditional"]
    for period, rows in sorted(by_period.items()):
        witnesses = _witnesses(rows)
        record = dict(period=period, source=source, witnesses=list(witnesses.values()))
        for side, team_id in zip(("home", "away"), ctx.team_ids):
            required = sorted(
                pid for pid, w in witnesses.items() if w["team_id"] == team_id
            )
            marked = []
            if period == 1:
                for player in teams[side + "Team"]["players"]:
                    position = player.get("position")
                    if position is not None and not isinstance(position, str):
                        raise ValueError(
                            "box-score position marker must be a string or null"
                        )
                    if position and position.strip():
                        marked.append(player["personId"])
                marked.sort()
            players = marked if len(marked) == 5 else required
            if period in manual:
                players = manual[period].get(side)
                if (
                    not isinstance(players, list)
                    or len(players) != 5
                    or any(type(p) is not int for p in players)
                    or len(set(players)) != 5
                ):
                    raise ValueError(
                        f"reviewed period {period} {side} requires five distinct player IDs"
                    )
                record["source"] = manual[period]["source"]
            if not set(required).issubset(players) or not set(marked).issubset(players):
                diagnostics.append(
                    V3Diagnostic(
                        "starters",
                        "conflicting_starters",
                        f"period {period} {side}: witnesses, position markers or review conflict",
                    )
                )
            if len(players) != 5:
                diagnostics.append(
                    V3Diagnostic(
                        "starters",
                        "missing_starters",
                        f"period {period} {side}: {len(players)} evidenced players; five required; no roster or prior-period completion",
                    )
                )
            if any(
                ctx.player(p) is None or ctx.player(p).team_id != team_id
                for p in players
            ):
                raise ValueError(
                    f"period {period} {side} starter is outside the team roster"
                )
            record[side] = sorted(players)
        if period == 1 and period not in manual:
            record[
                "source"
            ] += f"; Q1 uses exactly-five box-score position markers where available; boxscore sha256={box.source_sha256}"
        result.append(record)
        if any(len(record[side]) != 5 for side in ("home", "away")):
            pending.append(
                dict(period=period, home=record["home"], away=record["away"], source="")
            )
    return result, pending


def _batches(events, reviews, source, diagnostics):
    runs, prior = [], None
    for event in events.items:
        if event.kind != "substitution":
            prior = None
            continue
        key = (event.group.primary.period, event.group.primary.seconds_remaining_exact)
        if key != prior:
            runs.append([])
        runs[-1].append(event.group.primary.order)
        prior = key
    all_indices = {i for run in runs for i in run}
    accepted, covered = list(reviews.get("batches", [])), set()
    for record in accepted:
        indices = record.get("source_indices")
        if (
            not isinstance(indices, list)
            or not indices
            or any(type(i) is not int or i not in all_indices for i in indices)
        ):
            raise ValueError(
                "reviewed batch requires known substitution source_indices"
            )
        if len(set(indices)) != len(indices) or set(indices) & covered:
            raise ValueError("reviewed batches contain duplicate source_indices")
        covered.update(indices)
    pending = []
    for run in runs:
        missing = [i for i in run if i not in covered]
        if not missing:
            continue
        if len(run) == 1:
            accepted.append(
                dict(
                    source_indices=run,
                    source=f"Single substitution between non-substitution or different-clock boundaries; {source}",
                )
            )
        else:
            diagnostics.append(
                V3Diagnostic(
                    "batches",
                    "batch_review_required",
                    "Adjacent same-clock substitutions require reviewed batch membership; equal clocks alone are insufficient",
                    tuple(missing),
                )
            )
            # Separate remaining segments when part of a run has already been reviewed.
            segment = []
            for index in run + [None]:
                if index in missing:
                    segment.append(index)
                elif segment:
                    pending.append(dict(source_indices=segment, source=""))
                    segment = []
    return sorted(accepted, key=lambda r: r["source_indices"][0]), pending


def _replays(events, reviews, diagnostics):
    changed = {
        e.group.primary.order
        for e in events.items
        if e.kind == "replay"
        and e.subtype
        in ("Overturn Ruling", "Coach Challenge Overturn Ruling", "Challenge Changed")
    }
    records, covered = list(reviews.get("resolved_replays", [])), set()
    for record in records:
        index = record.get("source_index")
        if type(index) is not int or index not in changed or index in covered:
            raise ValueError("duplicate or extraneous reviewed replay")
        covered.add(index)
    pending = []
    for index in sorted(changed - covered):
        diagnostics.append(
            V3Diagnostic(
                "replays",
                "replay_review_required",
                "Changed replay needs a sourced final-snapshot resolution",
                (index,),
            )
        )
        pending.append(
            dict(
                source_index=index,
                resolution=None,
                affected_source_indices=[],
                source="",
            )
        )
    return records, pending


def _published_seconds(player):
    stats = player.get("statistics")
    value = stats.get("minutes") if isinstance(stats, dict) else None
    match = (
        re.fullmatch(r"([0-9]+):([0-9]+(?:\.[0-9]+)?)", value)
        if isinstance(value, str)
        else None
    )
    if match and Decimal(match[2]) <= 60:
        return Decimal(match[1]) * 60 + Decimal(match[2])
    # Older official page extracts put the DNP label in minutes itself.
    label = player.get("comment") if value == "" else value
    if isinstance(label, str) and re.match(r"^(?:DNP|DND|NWT)(?:\s*-|\s*$)", label):
        return Decimal(0)
    return None


def _reconcile_minutes(box, lineups, diagnostics):
    seconds = defaultdict(Decimal)
    # Independent of caller decimal context, including long fractional clocks.
    precision = max(
        40, sum(len(i.event.group.primary.get("clock")) for i in lineups.items) + 10
    )
    with localcontext(Context(prec=precision)):
        for item in lineups.items:
            clock = item.event.group.primary.seconds_remaining_exact
            if item.event.kind == "period_start":
                previous = clock
            for players in item.before.values():
                for pid in players:
                    seconds[pid] += previous - clock
            previous = clock
        for side in ("homeTeam", "awayTeam"):
            for player in box.source_data["boxScoreTraditional"][side]["players"]:
                published = _published_seconds(player)
                if published is None:
                    diagnostics.append(
                        V3Diagnostic(
                            "minutes",
                            "missing_minutes",
                            f"player {player['personId']}: supported published minutes or explicit DNP evidence required",
                        )
                    )
                    continue
                delta = seconds[player["personId"]] - published
                if abs(delta) > Decimal("0.5"):
                    diagnostics.append(
                        V3Diagnostic(
                            "minutes",
                            "minutes_conflict",
                            f"player {player['personId']}: reconstructed minus published seconds = {delta}",
                        )
                    )


def prepare_game(
    game_id,
    data_directory,
    *,
    league_id=None,
    snapshot_complete=False,
    substitution_stream_source,
    review=None,
    jump_ball_evidence=None,
    jump_ball_live=None,
):
    """Generate witnesses and a review template, then validate available evidence.

    ``substitution_stream_source`` explicitly attests complete substitution
    coverage. Its text is a caller assertion, not proof inferred from a roster.
    Multi-row substitution batches and changed replays are never auto-approved.
    """
    directory, box, raw, events, inputs = _load_inputs(
        game_id,
        data_directory,
        league_id,
        snapshot_complete,
        jump_ball_evidence,
        jump_ball_live,
    )
    with _stage(game_id, "preparation"):
        _text(
            substitution_stream_source,
            "substitution_stream_source (complete substitution coverage)",
        )
        fingerprints = lineup_fingerprints(events)
        reviewed, review_source = _reviews(game_id, directory, review, fingerprints)
        if review_source is not None and not isinstance(review, V3LineupEvidence):
            path = _path(directory, review)
            inputs["review"] = _file(path, review_source.source_bytes)
        source = f"On-court witnesses before any entrance in a complete substitution stream: {substitution_stream_source}; PBP sha256={inputs['pbp'].sha256}"
        diagnostics = []
        periods, pending_periods = _starters(events, box, reviewed, source, diagnostics)
        batches, pending_batches = _batches(events, reviewed, source, diagnostics)
        replays, pending_replays = _replays(events, reviewed, diagnostics)
        header = dict(schema_version=1, game_id=game_id, **fingerprints)
        candidate = dict(
            header, periods=periods, batches=batches, resolved_replays=replays
        )
        template = dict(
            header,
            periods=reviewed.get("periods", []) + pending_periods,
            batches=reviewed.get("batches", []) + pending_batches,
            resolved_replays=replays + pending_replays,
        )
        if not diagnostics:
            try:
                lineups = StatsNbaV3LineupLoader(
                    events,
                    V3LineupEvidence(
                        _json_bytes(candidate), "Prepared witness and reviewed evidence"
                    ),
                )
                _reconcile_minutes(box, lineups, diagnostics)
                StatsNbaV3PossessionLoader(lineups)
            except (ValueError, TypeError) as error:
                diagnostics.append(
                    V3Diagnostic("validation", "validation_failed", str(error))
                )
    return V3Preparation(candidate, template, diagnostics, inputs)
