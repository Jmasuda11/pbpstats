"""Offline native V3 integration with the shared possession engine."""

from collections import Counter, defaultdict

from pbpstats.data_loader.nba_possession_loader import NbaPossessionLoader
from pbpstats.data_loader.stats_nba_v3.lineups import StatsNbaV3LineupLoader
from pbpstats.data_loader.stats_nba_v3.shot_zones import StatsNbaV3ShotZoneLoader
from pbpstats.resources.enhanced_pbp.stats_nba_v3 import (
    EVENT_CLASSES,
    V3EndOfPeriod,
    V3FieldGoal,
    V3Foul,
    V3FreeThrow,
    V3JumpBall,
    V3Rebound,
    V3StartOfPeriod,
    V3TeamHeave,
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

    def __init__(self, lineups, *, shot_zones=None):
        if not isinstance(lineups, StatsNbaV3LineupLoader):
            raise TypeError("V3 possession loader requires StatsNbaV3LineupLoader")
        self.game_id, self.context = lineups.game_id, lineups.context
        self.rules = self.context.rules
        self.lineups = lineups
        self.use_v2_rules = lineups.use_v2_rules
        self.diagnostics = []
        if shot_zones is not None:
            if not isinstance(shot_zones, StatsNbaV3ShotZoneLoader):
                raise TypeError("shot_zones requires StatsNbaV3ShotZoneLoader")
            shot_zones.validate_lineups(lineups)
        self.shot_zones = shot_zones
        self.events = []
        for i, item in enumerate(lineups.items):
            if item.event.kind == "team_heave" and not self.rules.team_heave(
                item.event.group.primary.period,
                item.event.group.primary.seconds_remaining_exact,
            ):
                raise ValueError(
                    f"Stats V3 game {self.game_id}: team heave conflicts with league/season/clock"
                )
            event_class = EVENT_CLASSES.get(item.event.kind)
            if event_class is None:
                raise ValueError(
                    f"Stats V3 game {self.game_id}, source rows "
                    f"{item.event.group.source_indices}: unsupported possession kind {item.event.kind}"
                )
            event = event_class(item, i)
            if isinstance(event, V3FieldGoal):
                event.shot_zones = shot_zones
            self.events.append(event)
        self._link_and_score()
        self._validate_replays()
        self._associate_free_throws()
        self._validate_target_score()
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

    def _validate_replays(self):
        changed = {
            event.facts.group.primary.order: event
            for event in self.events
            if event.facts.kind == "replay"
            and event.facts.subtype
            in (
                "Overturn Ruling",
                "Coach Challenge Overturn Ruling",
                "Challenge Changed",
            )
        }
        records = self.lineups.evidence.data.get("resolved_replays", [])
        if not isinstance(records, list):
            raise ValueError("resolved_replays must be an array")
        rows = {r.order for e in self.events for r in e.facts.group.rows}
        covered = set()
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("resolved replay must be an object")
            index = record.get("source_index")
            if type(index) is not int or index not in changed or index in covered:
                raise ValueError("duplicate or extraneous resolved replay source_index")
            event = changed[index]
            if record.get("resolution") != "already_applied":
                raise event.error(
                    "replay correction requires an already-applied final snapshot"
                )
            source = record.get("source")
            affected = record.get("affected_source_indices")
            if not isinstance(source, str) or not source.strip():
                raise event.error("resolved replay requires source provenance")
            if (
                not isinstance(affected, list)
                or not affected
                or any(
                    type(i) is not int or i == index or i not in rows for i in affected
                )
                or len(set(affected)) != len(affected)
            ):
                raise event.error("resolved replay requires affected source rows")
            covered.add(index)
        for index in sorted(changed.keys() - covered):
            if self.use_v2_rules:
                self.diagnostics.append(dict(
                    stage="replays", code="final_snapshot_replay",
                    message="Replay retained in final snapshot under V2 rules; no reversal synthesized; scoring and sequence checks required.",
                    source_indices=changed[index].facts.group.source_indices,
                ))
                continue
            raise changed[index].error(
                "changed replay requires separate resolution evidence"
            )

    def _validate_target_score(self):
        overtime = [e for e in self.events if self.rules.untimed(e.period)]
        if not overtime:
            return
        start, end = overtime[0], overtime[-1]
        if (
            not isinstance(start, V3StartOfPeriod)
            or len(set(start.score.values())) != 1
        ):
            raise start.error("target-score overtime requires a tied regulation score")
        target = next(iter(start.score.values())) + 7
        reached = [e for e in overtime if max(e.score.values()) >= target]
        if not reached:
            raise end.error("target-score overtime ended before the target was reached")
        winner = reached[0]
        if not (
            isinstance(winner, V3FieldGoal)
            or isinstance(winner, V3FreeThrow)
            and winner.is_end_ft
        ):
            raise winner.error(
                "target-score ending requires a validated winning shot or terminal free throw"
            )
        if (
            len(reached) != 2
            or reached[1] is not end
            or not isinstance(end, V3EndOfPeriod)
            or end.seconds_remaining != winner.seconds_remaining
        ):
            raise winner.error(
                "target-score overtime must end immediately after the winning score"
            )
        self.overtime_target = target

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
                fouls_to_give = {
                    t: self.rules.fouls_to_give(event.period) for t in score
                }
            if self.rules.last_two_minutes(event.period, event.seconds_remaining):
                fouls_to_give = {t: min(n, 1) for t, n in fouls_to_give.items()}
            if isinstance(event, V3Foul):
                if event.is_transition_take_foul and not self.rules.transition_take(
                    event.period, event.seconds_remaining
                ):
                    raise event.error(
                        "transition take foul conflicts with league/period/clock"
                    )
                event.fouls_to_give_before = fouls_to_give.copy()
                if event.team_id not in score:
                    raise event.error("foul requires a game team")
                if event.counts_as_personal_foul:
                    player_fouls[event.player1_id] += 1
                if event.is_double_foul:
                    player_fouls[event.facts.participants.require_player("other_fouler")] += 1
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
                    ):
                        raise event.error(f"{field} conflicts with accumulated scoring")
                    if int(supplied) != score[team]:
                        if not self.use_v2_rules:
                            raise event.error(f"{field} conflicts with accumulated scoring")
                        self.diagnostics.append(dict(
                            stage="scoring", code="stale_score_annotation",
                            message=f"{field}={supplied}; event-derived score={score[team]}; raw annotation retained.",
                            source_indices=event.facts.group.source_indices,
                        ))
            roles = event.facts.participants.participants
            mappings = {
                "field_goal": {"assister": "player2_id", "blocker": "player3_id"},
                "team_heave": {"blocker": "player3_id"},
                "turnover": {"stealer": "player3_id"},
                "foul": {"foul_drawn": "player3_id", "other_fouler": "player3_id"},
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
        self._double_lane_restarts = {}
        for event in self.events:
            if not isinstance(event, V3FreeThrow):
                if (self.use_v2_rules and active is not None and isinstance(event, V3Turnover)
                        and active.facts.free_throw.category == "regular"
                        and active.facts.free_throw.attempt == active.facts.free_throw.total - 1
                        and (event.period, event.seconds_remaining, event.team_id)
                        == (active.period, active.seconds_remaining, active.team_id)):
                    # V2's recorded turnover ends possession, including a lane
                    # turnover instead of the final FT. Keep original numbering
                    # and actual attempts; an empty TO subtype stays unspecified.
                    self.diagnostics.append(dict(
                        stage="free_throws", code="ft_trip_ended_by_recorded_turnover",
                        message="Same-clock shooting-team turnover ends the pending trip before its final attempt; no attempt or turnover cause synthesized.",
                        source_indices=active.facts.group.source_indices + event.facts.group.source_indices,
                    ))
                    active = None
                if isinstance(event, V3Violation) and event.is_double_lane_violation:
                    if event not in self._double_lane_restarts:
                        self._bind_double_lane_restart(event, active)
                        active = None
                if active and (event.period, event.seconds_remaining) != (
                    active.period,
                    active.seconds_remaining,
                ):
                    raise event.error(
                        "incomplete free-throw trip before clock/period changes"
                    )
                if active and (
                    isinstance(event, (V3FieldGoal, V3Turnover, V3JumpBall))
                    or (isinstance(event, V3Foul) and not (event.is_technical or event.is_double_technical)
                        and not (self.use_v2_rules and event is active.trip_foul))
                ):
                    raise event.error(
                        "live event or unrelated foul interrupts free-throw trip"
                    )
                continue
            ft = event.facts.free_throw
            if ft.attempt == 1:
                if active is not None and not event.is_technical_ft:
                    raise event.error("overlapping free-throw trips")
                if active is not None and ft.total > 1:
                    raise event.error("numbered technical trip interrupts an active free-throw trip")
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
                    ft.category,
                    ft.total,
                    ft.attempt,
                ) != (
                    active.period,
                    active.seconds_remaining,
                    active.team_id,
                    previous.category,
                    previous.total,
                    previous.attempt + 1,
                ):
                    raise event.error(
                        "conflicting free-throw trip order, shooter, or clock"
                    )
                if event.player1_id != active.player1_id:
                    if not self.use_v2_rules:
                        raise event.error("conflicting free-throw trip order, shooter, or clock")
                    self.diagnostics.append(dict(
                        stage="free_throws", code="recorded_shooter_change",
                        message="Same-team free-throw trip continues with the recorded replacement shooter; no injury or fouled-player identity inferred.",
                        source_indices=active.facts.group.source_indices + event.facts.group.source_indices,
                    ))
                event.trip_foul = active.trip_foul
                if ft.category == "technical" and ft.total > 1:
                    event.technical_trip_fouls = active.technical_trip_fouls
                    event.trip_foul = event.technical_trip_fouls[ft.attempt - 1]
                active = None if ft.is_last_attempt else event
        if active is not None:
            raise active.error("incomplete free-throw trip")
        for foul in self.events:
            if (
                isinstance(foul, V3Foul)
                and (
                    foul.is_shooting_foul
                    or foul.is_technical
                    or foul.is_defensive_3_seconds
                    or foul.is_flagrant
                    or foul.is_clear_path_foul
                    or foul.is_transition_take_foul
                    or foul.is_away_from_play_foul
                    or (
                        (
                            foul.is_personal_foul
                            or foul.is_personal_take_foul
                            or foul.is_loose_ball_foul
                        )
                        and foul.fouls_to_give_before[foul.team_id] == 0
                    )
                )
                and foul not in consumed
            ):
                raise foul.error("missing free-throw trip for foul")

    def _bind_double_lane_restart(self, event, active):
        """A paired lane violation can cancel the unrecorded final attempt.

        NBA Rule 9-I-4 requires a jump ball when both teams violate the live
        final FT. Keep the original attempt numbering and never invent a miss.
        Other cancellation/retry sequences still require separate evidence.
        """
        if (self.rules.league_id != "00" or active is None
                or active.facts.free_throw.category != "regular"
                or active.facts.free_throw.attempt != active.facts.free_throw.total - 1
                or (active.period, active.seconds_remaining) != (event.period, event.seconds_remaining)):
            raise event.error("double lane requires evidence of the cancelled final free throw")
        pair, following = [], event
        while following is not None and following.seconds_remaining == event.seconds_remaining:
            if isinstance(following, V3Violation) and following.is_double_lane_violation:
                pair.append(following)
            elif following.facts.kind not in ("substitution", "replay", "timeout"):
                break
            following = following.next_event
        if (len(pair) != 2 or {e.team_id for e in pair} != set(self.context.team_ids)
                or not isinstance(following, V3JumpBall)
                or following.seconds_remaining != event.seconds_remaining):
            raise event.error("double lane requires opposing violations and a same-clock jump restart")
        for violation in pair:
            violation.facts.participants.require_player("actor")
            self._double_lane_restarts[violation] = following

    def _start_free_throw_trip(self, event, consumed):
        ft = event.facts.free_throw
        # V2 FieldGoal checks a same-team one-shot award at the basket's clock,
        # including personal/loose-ball fouls; the FT shooter need not be scorer.
        def basket_award(foul):
            if (self.rules.league_id != "00"
                    or not (foul.is_loose_ball_foul or self.use_v2_rules and foul.is_personal_foul)
                    or ft.category != "regular" or ft.total != 1):
                return None
            makes = [e for e in event.get_all_events_at_current_time()
                     if isinstance(e, V3FieldGoal) and e.is_made
                     and e.order < foul.order and e.team_id == event.team_id]
            return makes[0] if len(makes) == 1 else None

        candidates = []
        for foul in event.get_all_events_at_current_time():
            if (
                not isinstance(foul, V3Foul)
                or (not self.use_v2_rules and foul.order >= event.order)
                or foul in consumed
                or foul.team_id == event.team_id
            ):
                continue
            compatible = {
                "regular": foul.is_shooting_foul
                or basket_award(foul) is not None
                or (
                    (
                        foul.is_personal_foul
                        or foul.is_personal_take_foul
                        or foul.is_loose_ball_foul
                    )
                    and foul.fouls_to_give_before[foul.team_id] == 0
                    and ft.total * ft.points_per_attempt == 2
                )
                or foul.is_transition_take_foul
                or foul.is_away_from_play_foul,
                "technical": foul.is_technical or foul.is_defensive_3_seconds,
                "clear_path": foul.is_clear_path_foul,
                "flagrant": foul.is_flagrant,
            }[ft.category]
            if compatible:
                candidates.append(foul)
        if self.use_v2_rules:
            # FreeThrow.foul_that_led_to_ft in V2 searches backwards first,
            # then forwards at the same clock. Retain V3's unique-match and
            # shooter/award checks instead of taking an arbitrary nearby foul.
            preceding = [f for f in candidates if f.order < event.order]
            candidates = preceding or candidates
        repeated_technical = (
            event.is_technical_ft and len(candidates) > 1
            and all(f.is_technical for f in candidates)
            and len({(f.team_id, f.facts.subtype, f.facts.group.primary.get("personId")) for f in candidates}) == 1
        )
        if len(candidates) != 1 and not repeated_technical:
            raise event.error(
                "free-throw trip requires one unconsumed compatible "
                + ("" if self.use_v2_rules else "preceding ")
                + "foul at the exact clock, including penalty evidence for regular non-shooting trips"
            )
        foul = candidates[0]
        if (
            not self.use_v2_rules
            and not event.is_technical_ft
            and not foul.is_transition_take_foul
            and not foul.is_away_from_play_foul
            and hasattr(foul, "player3_id")
            and foul.player3_id != event.player1_id
        ):
            raise event.error("replacement shooter requires separate validation")
        if (self.use_v2_rules and not event.is_technical_ft
                and hasattr(foul, "player3_id") and foul.player3_id != event.player1_id):
            self.diagnostics.append(dict(
                stage="free_throws", code="recorded_shooter_differs_from_fouled_player",
                message="Recorded FT shooter and explicitly identified fouled player differ; both identities preserved without inferring an injury.",
                source_indices=foul.facts.group.source_indices + event.facts.group.source_indices,
            ))
        award = ft.total * ft.points_per_attempt
        retained = foul.is_transition_take_foul or foul.is_away_from_play_foul
        if retained:
            if event.player1_id not in foul.lineup.before[event.team_id]:
                raise event.error(
                    "retained-ball free-throw shooter was not on court at the foul"
                )
            if ft.category != "regular" or award != 1:
                raise event.error(
                    "take/away-from-play foul requires one retained-ball free throw"
                )
            event.is_transition_take_foul_ft = foul.is_transition_take_foul
            event.is_away_from_play_ft = foul.is_away_from_play_foul
        elif ft.category == "regular" and not foul.is_shooting_foul and basket_award(foul) is None:
            if award != 2 or foul.fouls_to_give_before[foul.team_id] != 0:
                raise event.error("regular non-shooting trip requires penalty evidence")
        consumed.add(foul)
        if event.is_technical_ft and ft.total > 1:
            if not self.use_v2_rules or not repeated_technical or len(candidates) != ft.total:
                raise event.error("numbered technical trip requires matching individual technical foul awards")
            consumed.update(candidates)
            event.technical_trip_fouls = tuple(candidates)
            for technical in candidates:
                technical.number_of_fta_for_foul = 1
        event.trip_foul = foul
        if not (event.is_technical_ft and ft.total > 1):
            foul.number_of_fta_for_foul = award
        if ft.category == "regular" and award == 1 and not retained:
            makes = [
                e
                for e in event.get_all_events_at_current_time()
                if isinstance(e, V3FieldGoal)
                and e.is_made
                and e.order < foul.order
                and e.team_id == event.team_id
                and (self.use_v2_rules or e.player1_id == event.player1_id or e is basket_award(foul))
            ]
            if len(makes) != 1 or not (foul.is_shooting_foul or basket_award(foul) is not None):
                raise event.error(
                    "one-shot regular trip requires a unique matching and-one; restart evidence is missing"
                )
            makes[0]._and_one = event
            if makes[0].player1_id != event.player1_id and self.use_v2_rules:
                self.diagnostics.append(dict(
                    stage="free_throws", code="different_shooter_after_made_basket",
                    message="Unique same-team basket linked to the one-shot award; recorded basket scorer and FT shooter preserved separately, without an injury inference.",
                    source_indices=makes[0].facts.group.source_indices + event.facts.group.source_indices,
                ))
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
            if isinstance(event, (V3FieldGoal, V3FreeThrow, V3TeamHeave)):
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
        same_clock = event.get_all_events_at_current_time()
        shot_clocks = [
            e
            for e in same_clock
            if isinstance(e, V3Turnover) and e.is_shot_clock_violation
            # An intervening shot starts a different rebound sequence, even
            # when rounded clocks coincide. Do not consume its later turnover.
            and not any(
                min(e.order, event.order) < other.order < max(e.order, event.order)
                and isinstance(
                    other,
                    (V3FieldGoal, V3FreeThrow, V3TeamHeave, V3JumpBall, V3Turnover),
                )
                for other in same_clock
            )
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
                    if self.use_v2_rules:
                        self._validate_v2_lane_context(event)
                        continue
                    before, after = event.previous_event, event.next_event
                    # A defensive lane violation between two made attempts in
                    # one validated trip cannot cancel either made free throw.
                    between_makes = (
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
                    )
                    if not between_makes and not self._is_shooter_lane_award(event):
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

    def _validate_v2_lane_context(self, event):
        """V2 Violation is passive; FT/rebound/turnover rules decide possession.

        A timeout, sub or replay is not an unknown restart. Keep the recorded
        final FT sequence rather than synthesizing an attempt, cancellation or
        turnover from a lane label. Trip, rebound and box-score checks still run.
        """
        related = [e for e in event.get_all_events_at_current_time()
                   if isinstance(e, V3FreeThrow) and not e.is_technical_ft
                   or isinstance(e, V3Turnover) and e.is_lane_violation]
        if not related:
            raise event.error("lane ruling has no same-clock free-throw or lane-turnover context")
        self.diagnostics.append(dict(
            stage="free_throws", code="lane_ruling_recorded_sequence",
            message="Lane violation retained as in V2; validated recorded FT, rebound and turnover events determine the outcome; no synthetic retry or possession boundary.",
            source_indices=event.facts.group.source_indices,
        ))

    def _is_shooter_lane_award(self, event):
        rebound = event.previous_event
        if (
            not isinstance(rebound, V3Rebound)
            or not rebound.is_real_rebound
            or rebound.player1_id
        ):
            return False
        miss = rebound.missed_shot
        return (
            isinstance(miss, V3FreeThrow)
            and not miss.is_made
            and miss.is_end_ft
            and rebound.previous_event is miss
            and event.player1_id == miss.player1_id
            and event.team_id == miss.team_id
            and rebound.team_id == self.context.other_team(miss.team_id)
            and event.seconds_remaining
            == rebound.seconds_remaining
            == miss.seconds_remaining
            and event.next_event is not None
            and event.next_event.seconds_remaining < event.seconds_remaining
        )

    def _set_period_offenses(self):
        for start in self.events:
            if not isinstance(start, V3StartOfPeriod):
                continue
            candidate = start.next_event
            while candidate is not None:
                if isinstance(
                    candidate, (V3FieldGoal, V3Turnover, V3JumpBall, V3TeamHeave)
                ) or (
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
                if isinstance(event, (V3FieldGoal, V3Turnover, V3TeamHeave)) or (
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
