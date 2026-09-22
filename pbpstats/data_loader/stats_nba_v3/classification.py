"""Classify native V3 facts without inferring lineups or possession boundaries."""

import re
from dataclasses import dataclass
from typing import Optional

from pbpstats.data_loader.stats_nba_v3.participants import (
    StatsNbaV3ParticipantLoader,
    V3ParticipantEvent,
)
from pbpstats.resources.league_rules import V3LeagueRules

# Exact provider vocabulary, deliberately bounded by recorded/synthetic tests.
# An unfamiliar shot style can retain explicit scoring facts; unfamiliar foul,
# turnover, violation, or replay semantics must not acquire a default meaning.
SUBTYPES = {
    "Foul": {
        "Personal",
        "Personal Take",
        "Away From Play",
        "Shooting",
        "Loose Ball",
        "Offensive",
        "Offensive Charge",
        "Technical",
        "Hanging Technical",
        "Defense 3 Second",
        "Clear Path",
        "Flagrant Type 1",
        "Flagrant Type 2",
        "Transition Take",
    },
    "Turnover": {
        "3 Second Violation",
        "5 Second Violation",
        "8 Second Violation",
        "Backcourt Turnover",
        "Bad Pass",
        "Lost Ball",
        "Offensive Foul Turnover",
        "Out of Bounds - Bad Pass Turnover",
        "Out of Bounds Lost Ball Turnover",
        "Step Out of Bounds Turnover",
        "Traveling",
        "Shot Clock Turnover",
        "Kicked Ball Violation",
        "Double Dribble",
    },
    "Violation": {
        "Defensive Goaltending",
        "Delay Of Game",
        "Kicked Ball",
        "Lane",
        "Jump Ball",
    },
    "Rebound": {"Normal Rebound", "Unknown"},
    "Substitution": {""},
    "Ejection": {"Other"},
    "Jump Ball": {""},
    "Timeout": {"Regular", "Official", "Reset", "Coach Challenge"},
    "Instant Replay": {
        "Coach Challenge Support Ruling",
        "Replay Center",
        "Support Ruling",
        "Ruling Stands",
        "Coach Challenge Ruling Stands",
        "Coach Challenge Overturn Ruling",
        "Overturn Ruling",
        "Challenge Changed",
    },
}
KINDS = {
    "Foul": "foul",
    "Turnover": "turnover",
    "Violation": "violation",
    "Rebound": "rebound",
    "Substitution": "substitution",
    "Ejection": "ejection",
    "Jump Ball": "jump_ball",
    "Timeout": "timeout",
    "Instant Replay": "replay",
}
FT_SUBTYPE = re.compile(r"Free Throw(?: (Clear Path|Flagrant))? ([1-3]) of ([1-3])")


@dataclass(frozen=True)
class V3FreeThrowFacts:
    category: str
    attempt: int
    total: int
    restart: str
    points_per_attempt: int = 1
    single_shot: bool = False

    @property
    def is_last_attempt(self):
        """Trip position only; never a declaration that a possession has ended."""
        return self.attempt == self.total


@dataclass(frozen=True)
class V3ClassifiedEvent:
    participants: V3ParticipantEvent
    kind: str
    recorded_points: int = 0
    shot_value: Optional[int] = None
    is_made: Optional[bool] = None
    attribution: Optional[str] = None
    free_throw: Optional[V3FreeThrowFacts] = None

    @property
    def group(self):
        return self.participants.group

    @property
    def team_id(self):
        return self.participants.team_id

    @property
    def subtype(self):
        return self.group.primary.sub_type

    @property
    def rebound_type(self):
        """Offensive/defensive/live/dead-ball classification needs shot context."""
        return None


def _error(event, message):
    group = event.group
    return ValueError(
        f"Stats V3 game {group.primary.game_id}, source rows {group.source_indices}: {message}"
    )


def _require_source(event, field, expected):
    value = event.group.primary.get(field)
    if type(value) is not type(expected) or value != expected:
        raise _error(event, f"{field} must be {expected!r}, got {value!r}")


def _require_scorer(event):
    if event.team_id is None:
        raise _error(event, "scoring event requires a team")
    event.require_player("actor")


def _field_goal(event):
    row = event.group.primary
    made = row.action_type == "Made Shot"
    _require_scorer(event)
    _require_source(event, "isFieldGoal", 1)
    _require_source(event, "shotResult", "Made" if made else "Missed")
    value = row.get("shotValue")
    if type(value) is not int or value not in (2, 3):
        raise _error(event, "field-goal shotValue must be 2 or 3")
    if (made and row.description.startswith("MISS ")) or (
        value == 2 and re.search(r"\b3PT\b", row.description)
    ):
        raise _error(event, "shot description conflicts with explicit scoring fields")
    return V3ClassifiedEvent(
        event, "field_goal", value if made else 0, value, made, "player"
    )


def _free_throw(event):
    row = event.group.primary
    _require_scorer(event)
    match = FT_SUBTYPE.fullmatch(row.sub_type)
    single = re.fullmatch(r"Free Throw ([1-3])PT", row.sub_type)
    value = int(single[1]) if single else 1
    rules = V3LeagueRules.for_game(row.game_id)
    if row.sub_type == "Free Throw Technical":
        category, attempt, total, restart = "technical", 1, 1, "resume_interrupted_play"
    elif single:
        if not rules.single_free_throw(row.period, row.seconds_remaining_exact):
            raise _error(
                event, "single-shot free throw conflicts with league/season/clock"
            )
        category, attempt, total, restart = "regular", 1, 1, "context_required"
    elif match:
        category = {
            None: "regular",
            "Clear Path": "clear_path",
            "Flagrant": "flagrant",
        }[match[1]]
        attempt, total = int(match[2]), int(match[3])
        if attempt > total or (category == "clear_path" and total != 2):
            raise _error(event, "invalid free-throw attempt/total")
        if total > 1 and rules.single_free_throw(
            row.period, row.seconds_remaining_exact
        ):
            raise _error(
                event, "multi-attempt trip conflicts with G League single-shot period"
            )
        # An ordinary subtype does not identify the foul or prove the restart:
        # away-from-play/inbound/take fouls and corrections need later linkage.
        restart = (
            "context_required" if category == "regular" else "shooting_team_retains"
        )
    else:
        raise _error(event, f"unsupported free-throw subtype {row.sub_type!r}")
    pattern = rf"(?P<miss>MISS )?(?P<name>.+) {re.escape(row.sub_type)}(?P<points> \([0-9]+ PTS\))?"
    description = re.fullmatch(pattern, row.description)
    if description is None:
        raise _error(
            event, "free-throw description is missing or conflicts with subtype"
        )
    # Recorded FT rows carry blank shotResult and zero shotValue. The exact,
    # recognized description establishes the recorded outcome, not those flags.
    made = description["miss"] is None
    if made == (description["points"] is None):
        raise _error(
            event, "free-throw description lacks or contradicts outcome evidence"
        )
    facts = V3FreeThrowFacts(category, attempt, total, restart, value, bool(single))
    return V3ClassifiedEvent(
        event, "free_throw", value if made else 0, value, made, "player", facts
    )


def classify_event(event):
    """Return a typed fact, retaining every row and unresolved participant role."""
    if not isinstance(event, V3ParticipantEvent):
        raise TypeError("classify_event requires a V3ParticipantEvent")
    row = event.group.primary
    if row.action_type in ("Made Shot", "Missed Shot"):
        return _field_goal(event)
    for field, expected in (("isFieldGoal", 0), ("shotValue", 0), ("shotResult", "")):
        _require_source(event, field, expected)
    if row.action_type == "Free Throw":
        return _free_throw(event)
    if row.action_type == "period" and row.sub_type in ("start", "end"):
        return V3ClassifiedEvent(event, f"period_{row.sub_type}")
    if row.action_type == "Heave" and row.sub_type == "Team Field Goal Attempt":
        if (
            event.team_id is None
            or event.participants["actor"].status != "not_applicable"
        ):
            raise _error(event, "team heave requires team-only attribution")
        return V3ClassifiedEvent(event, "team_heave", attribution="team")
    if row.sub_type not in SUBTYPES.get(row.action_type, set()):
        raise _error(
            event, f"unsupported event semantics {row.action_type!r}/{row.sub_type!r}"
        )
    return V3ClassifiedEvent(event, KINDS[row.action_type])


class StatsNbaV3EventLoader:
    """Classify participant facts; no stats, ordering repairs, or hidden I/O.

    Required scoring evidence must be present. Other unresolved participant
    roles survive for later consumers to validate before depending on them.
    ``recorded_points`` is row-level evidence, not correction-reconciled scoring.
    """

    def __init__(self, participant_loader):
        if not isinstance(participant_loader, StatsNbaV3ParticipantLoader):
            raise TypeError(
                "StatsNbaV3EventLoader requires StatsNbaV3ParticipantLoader"
            )
        self.game_id = participant_loader.game_id
        self.context = participant_loader.context
        self.snapshot_complete = participant_loader.snapshot_complete
        self.items = tuple(classify_event(event) for event in participant_loader.items)
