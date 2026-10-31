"""
``V3Possession`` is the original's :obj:`~pbpstats.resources.possessions.possession.Possession`
for possessions of native V3 events, with one of its defects guarded and reviewed clock resets
"""
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
