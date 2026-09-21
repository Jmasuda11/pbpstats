"""Offline native V3 integration with the shared possession engine."""

from collections import Counter, defaultdict

from pbpstats.data_loader.nba_possession_loader import NbaPossessionLoader
from pbpstats.data_loader.stats_nba_v3.lineups import StatsNbaV3LineupLoader
from pbpstats.resources.enhanced_pbp.stats_nba_v3 import (
    EVENT_CLASSES,
    V3EndOfPeriod,
    V3FieldGoal,
    V3Foul,
    V3FreeThrow,
    V3JumpBall,
    V3Rebound,
    V3StartOfPeriod,
    V3Turnover,
    V3Violation,
)
from pbpstats.resources.possessions.possession import Possession


class StatsNbaV3PossessionLoader(NbaPossessionLoader):
    """Build standard Possession objects from an already validated lineup loader.

    This explicit entry point does not register a Client provider, repair source
    rows, read override files, or fetch missing evidence. Full event statistics
    remain unavailable; shared ``base_stats`` cover possession/time accounting.
    """

    def __init__(self, lineups):
        if not isinstance(lineups, StatsNbaV3LineupLoader):
            raise TypeError("V3 possession loader requires StatsNbaV3LineupLoader")
        self.game_id, self.context = lineups.game_id, lineups.context
        if not self.game_id.startswith("00"):
            raise ValueError("V3 possession rules currently support NBA games only")
        self.lineups = lineups
        self.events = []
        for i, item in enumerate(lineups.items):
            event_class = EVENT_CLASSES.get(item.event.kind)
            if event_class is None:
                raise ValueError(
                    f"Stats V3 game {self.game_id}, source rows "
                    f"{item.event.group.source_indices}: unsupported possession kind {item.event.kind}"
                )
            self.events.append(event_class(item, i))
        self._link_and_score()
        self._associate_free_throws()
        self._associate_rebounds()
        self._validate_restart_evidence()
        self._set_period_offenses()
        self.items = [Possession(group) for group in self._split_events_by_possession()]
        if sum(len(p.events) for p in self.items) != len(self.events):
            raise ValueError(
                f"Stats V3 game {self.game_id}: unclosed possession events"
            )
        self._add_extra_attrs_to_all_possessions()
        self._validate_possessions()

    def _link_and_score(self):
        score = {team: 0 for team in self.context.team_ids}
        player_fouls = defaultdict(int)
        for i, event in enumerate(self.events):
            event.previous_event = (
                self.events[i - 1]
                if i and self.events[i - 1].period == event.period
                else None
            )
            event.next_event = (
                self.events[i + 1]
                if i + 1 < len(self.events)
                and self.events[i + 1].period == event.period
                else None
            )
            if isinstance(event, V3StartOfPeriod):
                fouls_to_give = {t: 4 if event.period <= 4 else 3 for t in score}
            if event.seconds_remaining <= 120:
                fouls_to_give = {t: min(n, 1) for t, n in fouls_to_give.items()}
            if isinstance(event, V3Foul):
                event.fouls_to_give_before = fouls_to_give.copy()
                if event.team_id not in score:
                    raise event.error("foul requires a game team")
                if event.counts_as_personal_foul:
                    player_fouls[event.player1_id] += 1
                if event.counts_towards_penalty:
                    fouls_to_give[event.team_id] = max(
                        0, fouls_to_give[event.team_id] - 1
                    )
            event.fouls_to_give = fouls_to_give.copy()
            event.player_game_fouls = player_fouls.copy()
            if event.facts.recorded_points:
                score[event.team_id] += event.facts.recorded_points
            event.score = score.copy()
            for field, team in (
                ("scoreHome", self.context.home_team_id),
                ("scoreAway", self.context.away_team_id),
            ):
                supplied = event.facts.group.primary.get(field)
                if supplied not in (None, ""):
                    if (
                        not isinstance(supplied, str)
                        or not supplied.isdecimal()
                        or int(supplied) != score[team]
                    ):
                        raise event.error(f"{field} conflicts with accumulated scoring")
            roles = event.facts.participants.participants
            mappings = {
                "field_goal": {"assister": "player2_id", "blocker": "player3_id"},
                "turnover": {"stealer": "player3_id"},
                "foul": {"foul_drawn": "player3_id"},
                "substitution": {"incoming": "player2_id"},
                "jump_ball": {
                    "tip_recipient": "player2_id",
                    "opposing_jumper": "player3_id",
                },
            }
            for role, attr in mappings.get(event.facts.kind, {}).items():
                if role in roles and roles[role].player_id is not None:
                    setattr(event, attr, roles[role].player_id)
            if isinstance(event, V3JumpBall):
                event.team_id = roles["tip_recipient"].team_id

    def _associate_free_throws(self):
        consumed = set()
        active = None
        for event in self.events:
            if not isinstance(event, V3FreeThrow):
                if active and (event.period, event.seconds_remaining) != (
                    active.period,
                    active.seconds_remaining,
                ):
                    raise event.error(
                        "incomplete free-throw trip before clock/period changes"
                    )
                if active and (
                    isinstance(event, (V3FieldGoal, V3Turnover, V3JumpBall))
                    or (isinstance(event, V3Foul) and not event.is_technical)
                ):
                    raise event.error(
                        "live event or unrelated foul interrupts free-throw trip"
                    )
                continue
            ft = event.facts.free_throw
            if ft.attempt == 1:
                if active is not None and not event.is_technical_ft:
                    raise event.error("overlapping free-throw trips")
                self._start_free_throw_trip(event, consumed)
                if ft.total > 1:
                    active = event
            else:
                if active is None:
                    raise event.error("free-throw trip does not start at attempt 1")
                previous = active.facts.free_throw
                if (
                    event.period,
                    event.seconds_remaining,
                    event.team_id,
                    event.player1_id,
                    ft.category,
                    ft.total,
                    ft.attempt,
                ) != (
                    active.period,
                    active.seconds_remaining,
                    active.team_id,
                    active.player1_id,
                    previous.category,
                    previous.total,
                    previous.attempt + 1,
                ):
                    raise event.error(
                        "conflicting free-throw trip order, shooter, or clock"
                    )
                event.trip_foul = active.trip_foul
                active = None if ft.is_last_attempt else event
        if active is not None:
            raise active.error("incomplete free-throw trip")
        for foul in self.events:
            if (
                isinstance(foul, V3Foul)
                and (
                    foul.is_shooting_foul
                    or foul.is_technical
                    or foul.is_flagrant
                    or foul.is_clear_path_foul
                    or (
                        (foul.is_personal_foul or foul.is_loose_ball_foul)
                        and foul.fouls_to_give_before[foul.team_id] == 0
                    )
                )
                and foul not in consumed
            ):
                raise foul.error("missing free-throw trip for foul")

    def _start_free_throw_trip(self, event, consumed):
        ft = event.facts.free_throw
        candidates = []
        for foul in event.get_all_events_at_current_time():
            if (
                not isinstance(foul, V3Foul)
                or foul.order >= event.order
                or foul in consumed
                or foul.team_id == event.team_id
            ):
                continue
            compatible = {
                "regular": foul.is_shooting_foul
                or foul.is_personal_foul
                or foul.is_loose_ball_foul,
                "technical": foul.is_technical,
                "clear_path": foul.is_clear_path_foul,
                "flagrant": foul.is_flagrant,
            }[ft.category]
            if compatible:
                candidates.append(foul)
        if len(candidates) != 1:
            raise event.error(
                "free-throw trip requires one unconsumed compatible preceding foul at the exact clock"
            )
        foul = candidates[0]
        if (
            not event.is_technical_ft
            and hasattr(foul, "player3_id")
            and foul.player3_id != event.player1_id
        ):
            raise event.error("replacement shooter requires separate validation")
        if ft.category == "regular" and not foul.is_shooting_foul:
            if ft.total != 2 or foul.fouls_to_give_before[foul.team_id] != 0:
                raise event.error("regular non-shooting trip requires penalty evidence")
        consumed.add(foul)
        event.trip_foul = foul
        foul.number_of_fta_for_foul = ft.total
        if ft.category == "regular" and ft.total == 1:
            makes = [
                e
                for e in event.get_all_events_at_current_time()
                if isinstance(e, V3FieldGoal)
                and e.is_made
                and e.order < foul.order
                and e.team_id == event.team_id
                and e.player1_id == event.player1_id
            ]
            if len(makes) != 1 or not foul.is_shooting_foul:
                raise event.error(
                    "one-shot regular trip requires a unique matching and-one; restart evidence is missing"
                )
            makes[0]._and_one = event
        if ft.category in ("clear_path", "flagrant"):
            makes = [
                e
                for e in event.get_all_events_at_current_time()
                if isinstance(e, V3FieldGoal) and e.is_made and e.order < foul.order
            ]
            if makes:
                if (
                    ft.category != "flagrant"
                    or len(makes) != 1
                    or makes[0].team_id != event.team_id
                ):
                    raise event.error(
                        "unsupported retained-ball foul after a made shot"
                    )
                makes[0]._retained_make = True

    def _associate_rebounds(self):
        pending = None
        used_shot_clocks = set()
        for event in self.events:
            if isinstance(event, (V3FieldGoal, V3FreeThrow)):
                if pending is not None:
                    raise event.error(
                        "missing rebound evidence for preceding missed shot"
                    )
                if not event.is_made:
                    pending = event
            elif isinstance(event, V3Rebound):
                if event.team_id not in self.context.team_ids:
                    raise event.error("rebound requires a game team")
                reason = self._rebound_placeholder_reason(
                    event, pending, used_shot_clocks
                )
                if reason and event.player1_id != 0:
                    raise event.error(
                        "non-live rebound contradicts an explicit player rebound"
                    )
                event._missed_shot = pending
                event.placeholder_reason = reason
                pending = None
            elif isinstance(event, V3EndOfPeriod) and pending is not None:
                raise event.error("unresolved missed shot at period end")
            elif (
                isinstance(event, V3Turnover)
                and not event.is_shot_clock_violation
                and pending is not None
            ):
                raise event.error("unresolved missed shot before turnover")

    def _rebound_placeholder_reason(self, event, pending, used_shot_clocks):
        shot_clocks = [
            e
            for e in event.get_all_events_at_current_time()
            if isinstance(e, V3Turnover) and e.is_shot_clock_violation
        ]
        if shot_clocks and event.player1_id == 0:
            if len(shot_clocks) != 1 or shot_clocks[0] in used_shot_clocks:
                raise event.error("ambiguous or reused shot-clock rebound evidence")
            used_shot_clocks.add(shot_clocks[0])
            return "shot_clock_turnover"
        if pending is None or pending.period != event.period:
            raise event.error("rebound has no unconsumed missed shot")
        if isinstance(pending, V3FreeThrow) and not pending.is_end_ft:
            if event.seconds_remaining != pending.seconds_remaining:
                raise event.error("non-live rebound conflicts with free-throw clock")
            return "non_live_free_throw"
        if event.player1_id == 0 and event.seconds_remaining == 0:
            return "period_expired"
        if (
            event.player1_id == 0
            and pending.seconds_remaining == event.seconds_remaining
            and event.seconds_remaining <= 3
        ):
            following = event.next_event
            while following and following.facts.kind == "replay":
                following = following.next_event
            if isinstance(following, V3EndOfPeriod):
                return "buzzer_placeholder"
        return None

    def _validate_restart_evidence(self):
        for event in self.events:
            if isinstance(event, V3Violation):
                if event.is_lane_violation:
                    before, after = event.previous_event, event.next_event
                    # A defensive lane violation between two made attempts in
                    # one validated trip cannot cancel either made free throw.
                    if not (
                        isinstance(before, V3FreeThrow)
                        and before.is_made
                        and isinstance(after, V3FreeThrow)
                        and after.is_made
                        and before.trip_foul is after.trip_foul
                        and before.seconds_remaining
                        == event.seconds_remaining
                        == after.seconds_remaining
                        and event.team_id in self.context.team_ids
                        and event.team_id != before.team_id
                    ):
                        raise event.error(
                            "lane ruling requires separate retry/restart evidence"
                        )
                if event.is_goaltend_violation:
                    makes = [
                        e
                        for e in event.get_all_events_at_current_time()
                        if isinstance(e, V3FieldGoal)
                        and e.is_made
                        and e.team_id != event.team_id
                    ]
                    if len(makes) != 1:
                        raise event.error(
                            "goaltending requires one matching awarded field goal"
                        )
            if isinstance(event, V3Foul) and (
                event.is_offensive_foul or event.is_charge
            ):
                turnovers = [
                    e
                    for e in event.get_all_events_at_current_time()
                    if isinstance(e, V3Turnover)
                    and e.facts.subtype == "Offensive Foul Turnover"
                    and (e.team_id, e.player1_id) == (event.team_id, event.player1_id)
                ]
                if len(turnovers) != 1:
                    raise event.error("offensive foul requires one matching turnover")

    def _set_period_offenses(self):
        for start in self.events:
            if not isinstance(start, V3StartOfPeriod):
                continue
            candidate = start.next_event
            while candidate is not None:
                if isinstance(candidate, (V3FieldGoal, V3Turnover, V3JumpBall)) or (
                    isinstance(candidate, V3FreeThrow) and not candidate.is_technical_ft
                ):
                    if isinstance(candidate, V3JumpBall) and (
                        candidate.seconds_remaining != start.seconds_remaining
                    ):
                        raise candidate.error(
                            "interior jump lacks preceding offense evidence"
                        )
                    start.team_starting_with_ball = candidate.team_id
                    break
                candidate = candidate.next_event
            else:
                raise start.error("period lacks evidence of the starting offense")
            candidate = start
            while candidate is not None:
                candidate.initial_offense_team_id = start.team_starting_with_ball
                candidate = candidate.next_event

    def _validate_possessions(self):
        for possession in self.items:
            offense = possession.offense_team_id
            if offense not in self.context.team_ids:
                raise possession.events[0].error("possession offense is unresolved")
            previous = possession.previous_possession
            if previous and previous.offense_team_id == offense:
                raise possession.events[0].error(
                    "back-to-back possessions require additional restart evidence"
                )
            for event in possession.events:
                if isinstance(event, (V3FieldGoal, V3Turnover)) or (
                    isinstance(event, V3FreeThrow) and not event.is_technical_ft
                ):
                    if event.team_id != offense:
                        raise event.error(
                            "offensive event conflicts with possession offense"
                        )
                # Evaluate dependencies eagerly, before exposing any partial result.
                event.base_stats

    @property
    def counts_by_team(self):
        """Credited possessions, which need not equal the number of groups."""
        counts = Counter({team: 0 for team in self.context.team_ids})
        for possession in self.items:
            if possession.events[-1].count_as_possession:
                counts[possession.offense_team_id] += 1
        return dict(counts)

    @property
    def base_stats(self):
        """Shared player/lineup time and possession stats only, with exact seconds."""
        return [stat for event in self.events for stat in event.base_stats]
