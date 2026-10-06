"""Versioned team-only miss; shared rebound/possession methods are unchanged."""

from pbpstats.resources.enhanced_pbp.stats_nba.field_goal import StatsFieldGoal


TEAM_HEAVE_VERSION = "nba_recorded_team_heave_v1"


class V3TeamHeave(StatsFieldGoal):
    """A recorded NBA team heave, not an inferred player shot or V2 code.

    The existing statistical convention uses player 0 for team attribution.
    A separately recorded blocker/rebounder still receives individual credit.
    Zero-filled native shot coordinates are absent facts, not a rim location.
    """

    event_action_type = None
    is_team_heave = True
    extension_version = TEAM_HEAVE_VERSION
    is_made = False
    shot_value = 3
    is_heave = True
    is_corner_3 = False
    is_putback = False
    distance = None
    locX = None
    locY = None

    @property
    def shot_data(self):
        return dict(super().shot_data, IsTeamHeave=True, Attribution="team")

    @property
    def event_stats(self):
        # Original field-goal statistics already attribute the miss to player 0.
        # Its distance gate skips the heave counter because distance is unknown.
        stats = super().event_stats
        heave = self._get_heave_stat_item()
        opponent = next(t for t in self.current_players if t != self.team_id)
        heave.update(
            lineup_id=self.lineup_ids[self.team_id],
            opponent_team_id=opponent,
            opponent_lineup_id=self.lineup_ids[opponent],
        )
        return stats + [heave]
