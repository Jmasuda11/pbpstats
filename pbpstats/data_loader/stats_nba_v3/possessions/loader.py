"""
``StatsNbaV3PossessionLoader`` loads possession data for a game and
creates :obj:`~pbpstats.resources.possessions.possession.Possession` objects for each possession,
from native V3 events with the original's possession decisions

The following code will load possession data for game id "0022500001" from files
located in subdirectories of the /data directory

.. code-block:: python

    from pbpstats.data_loader import StatsNbaV3PossessionFileLoader, StatsNbaV3PossessionLoader

    source_loader = StatsNbaV3PossessionFileLoader("/data")
    possession_loader = StatsNbaV3PossessionLoader("0022500001", source_loader)
    print(possession_loader.items[0].data)  # prints dict with the first possession of the game
"""
from collections import Counter
from copy import deepcopy

from pbpstats.data_loader.stats_nba.possessions.loader import StatsNbaPossessionLoader
from pbpstats.data_loader.stats_nba_v3.decoder import (
    BLANK_FLAGRANT_FREE_THROW_VERSION,
    TEAMLESS_EXCESS_TIMEOUT_VERSION,
    TEAMLESS_TECHNICAL_VERSION,
    TECHNICAL_FREE_THROW_VERSION,
    TRANSITION_TAKE_FOUL_VERSION,
    VOIDED_SECOND_FREE_THROW_VERSION,
    V3DecodeError,
)
from pbpstats.data_loader.stats_nba_v3.enhanced_pbp.loader import (
    AND_ONE_CLOCK_VERSION,
    StatsNbaV3EnhancedPbpLoader,
    V3HeldBallJumpBall,
)
from pbpstats.data_loader.stats_nba_v3.held_ball import HELD_BALL_VERSION
from pbpstats.data_loader.stats_nba_v3.overrides import BAD_POSSESSIONS
from pbpstats.data_loader.stats_nba_v3.team_heave import TEAM_HEAVE_VERSION
from pbpstats.resources.enhanced_pbp import Substitution
from pbpstats.resources.possessions.possession import Possession


TEAM_IDS_GUARD = "possession_team_ids_skip_teamless_events_v1"


class V3Possession(Possession):
    """Original Possession with one defect guarded and reviewed clock resets.

    The original get_team_ids skips team-less events in its own possession but
    not in neighbouring ones. Replay events never have a team, in V2 or V3, so
    a lone jump-ball possession after a replay review raised AttributeError.
    Wherever the original returns, this returns the identical list.

    A possession that follows a reviewed game-clock reset starts at the clock
    the reset set, not at the previous possession's last clock.
    """

    @property
    def start_time(self):
        previous = getattr(self, "previous_possession", None)
        reset = getattr(previous.events[-1], "reviewed_clock_reset", None) if previous else None
        return reset if reset is not None else super().start_time

    def get_team_ids(self):
        def team_ids_of(possession):
            return [
                event.team_id
                for event in possession.events
                if hasattr(event, "team_id") and event.team_id != 0
            ]

        team_ids = list(set(team_ids_of(self)))
        prev_poss = self.previous_possession
        while len(team_ids) != 2 and prev_poss is not None:
            team_ids += team_ids_of(prev_poss)
            team_ids = list(set(team_ids))
            prev_poss = prev_poss.previous_possession
        next_poss = self.next_possession
        while len(team_ids) != 2 and next_poss is not None:
            team_ids += team_ids_of(next_poss)
            team_ids = list(set(team_ids))
            next_poss = next_poss.next_possession
        return team_ids


class StatsNbaV3PossessionLoader(StatsNbaPossessionLoader):
    """
    Loads stats.nba.com source play-by-play V3 possession data for game.
    Possessions are stored in items attribute as :obj:`~pbpstats.resources.possessions.possession.Possession` objects

    Native V3 event classes; the original's enhancement and possession
    decisions. Detailed V3 stats are gated.

    :param str game_id: NBA Stats Game Id
    :param source_loader: :obj:`~pbpstats.data_loader.stats_nba_v3.possessions.file.StatsNbaV3PossessionFileLoader` or :obj:`~pbpstats.data_loader.stats_nba_v3.possessions.web.StatsNbaV3PossessionWebLoader` object
    :raises: :obj:`~pbpstats.data_loader.stats_nba.possessions.loader.TeamHasBackToBackPossessionsException`:
        If team has the ball on back-to-back possessions.
    """

    data_provider = "stats_nba_v3"
    resource = "Possessions"
    parent_object = "Game"

    def __init__(self, game_id, source_loader):
        self._load(
            StatsNbaV3EnhancedPbpLoader(game_id, source_loader.enhanced_pbp_source_loader)
        )

    @classmethod
    def from_context(
        cls,
        source_bytes,
        context,
        *,
        validate_possessions=True,
        validate_source_order=True,
        **options,
    ):
        """Possessions from recorded V3 bytes and a given game context, with no I/O.

        ``validate_possessions=False`` is for differential event-sequence
        fixtures; it is not a declaration of full-game validity. ``options``
        are :obj:`StatsNbaV3EnhancedPbpLoader.from_context`'s.
        """
        enhanced = StatsNbaV3EnhancedPbpLoader.from_context(
            source_bytes, context, validate_source_order=validate_source_order, **options
        )
        loader = cls.__new__(cls)
        loader._load(enhanced, validate_possessions, validate_source_order)
        return loader

    def _load(self, enhanced, validate_possessions=True, validate_source_order=True):
        self.overrides = enhanced.overrides
        self.decoded = decoded = enhanced.decoded
        self.game_id = enhanced.game_id
        self.file_directory = enhanced.file_directory
        self.events = enhanced.items
        self.diagnostics = (
            enhanced.override_diagnostics + enhanced.repairs
            + deepcopy(list(decoded.team_heaves.values()))
            + deepcopy(decoded.team_technicals)
            + deepcopy(decoded.label_rules)
            + deepcopy(decoded.non_roster_actors)
            + deepcopy(decoded.reviewed_inputs)
            + ([dict(decoded.live_input)] if decoded.live_input else [])
            + deepcopy(decoded.recorded_jump_balls)
        )
        self.items = [
            V3Possession(events) for events in self._split_events_by_possession()
        ]
        self._add_extra_attrs_to_all_possessions()
        held_balls = [
            event.diagnostic
            for event in self.events
            if isinstance(event, V3HeldBallJumpBall)
            and event.held_ball_turnover is not None
        ]
        self.diagnostics += held_balls
        if sum(len(possession.events) for possession in self.items) != len(self.events):
            raise V3DecodeError("Events left outside a possession")
        if any(
            getattr(event, "reviewed_clock_reset", None) is not None
            for possession in self.items
            for event in possession.events[:-1]
        ):
            raise V3DecodeError("A reviewed clock reset must end a possession")
        self._validate_lineups()
        if validate_possessions:
            self._load_bad_possession_overrides()
            self._check_that_possessions_alternate()
        self.capabilities = {
            "processing_rules": "original_v2_e7ccf2f",
            "full_game_validated": False,
            "detailed_event_stats": "unavailable",
            "source_order_checked": validate_source_order,
            "possession_sequence_checked": validate_possessions,
            "defect_guards": [TEAM_IDS_GUARD],
        }
        extensions = [TEAM_HEAVE_VERSION] if decoded.team_heaves else []
        rules = {
            rule.get("code")
            for rule in decoded.team_technicals + decoded.label_rules + enhanced.repairs
        }
        extensions += [
            version
            for version in (
                TEAMLESS_TECHNICAL_VERSION,
                TEAMLESS_EXCESS_TIMEOUT_VERSION,
                TECHNICAL_FREE_THROW_VERSION,
                TRANSITION_TAKE_FOUL_VERSION,
                BLANK_FLAGRANT_FREE_THROW_VERSION,
                VOIDED_SECOND_FREE_THROW_VERSION,
                AND_ONE_CLOCK_VERSION,
            )
            if version in rules
        ]
        if held_balls:
            extensions.append(HELD_BALL_VERSION)
        if extensions:
            self.capabilities["extensions"] = extensions

    def _load_bad_possession_overrides(self):
        self.bad_pbp_cases = deepcopy(self.overrides.get(BAD_POSSESSIONS, {}))

    def _validate_lineups(self):
        resolved = {r["event_num"]: r for r in self.decoded.participant_resolutions}
        # A reviewed outgoing player replaces the one V3 records already off
        # the floor, so the recorded player must be off it.
        recorded_outgoing = {
            d["event_num"]: d["recorded_player_id"]
            for d in self.decoded.reviewed_inputs
            if d["code"] == "reviewed_substitution_outgoing"
        }
        for event in self.events:
            if event.event_num in resolved:
                actual = sorted(
                    p for players in event.current_players.values() for p in players
                )
                if actual != resolved[event.event_num]["on_court"]:
                    raise V3DecodeError(
                        "Participant resolution disagrees with original enhanced lineup at event {}".format(
                            event.event_num
                        )
                    )
            if isinstance(event, Substitution):
                before = event.previous_event.current_players
                if (
                    event.player1_id not in before[event.team_id]
                    or event.player2_id in before[event.team_id]
                ):
                    raise V3DecodeError(
                        "Substitution contradicts current lineup at event {}".format(
                            event.event_num
                        )
                    )
                if (
                    event.event_num in recorded_outgoing
                    and recorded_outgoing[event.event_num] in before[event.team_id]
                ):
                    raise V3DecodeError(
                        "Event substitution-outgoing override does not fit the recorded event"
                    )
            for team, players in event.current_players.items():
                if len(players) != 5 or len(set(players)) != 5:
                    raise V3DecodeError(
                        "Invalid five-player lineup at event {}".format(event.event_num)
                    )
                if any(
                    player not in self.decoded.context.roster
                    or self.decoded.context.roster[player]["team_id"] != team
                    for player in players
                ):
                    raise V3DecodeError("Lineup contradicts roster")

    @property
    def counts_by_team(self):
        return dict(
            Counter(
                p.offense_team_id
                for p in self.items
                if p.events[-1].count_as_possession
            )
        )

    @property
    def base_stats(self):
        return [stat for event in self.events for stat in event.base_stats]

    @property
    def event_stats(self):
        raise V3DecodeError(
            "Detailed statistics are unavailable until attribution completeness is verified"
        )
