from pbpstats.resources.enhanced_pbp import Foul
from pbpstats.resources.enhanced_pbp.stats_nba_v3.enhanced_pbp_item import (
    StatsNbaV3EnhancedPbpItem,
)


class StatsNbaV3Foul(Foul, StatsNbaV3EnhancedPbpItem):
    """
    Class for foul events
    """

    @property
    def number_of_fta_for_foul(self):
        """
        returns the number of free throws resulting from the foul
        """
        clock = self.clock
        event = self
        while (
            event is not None
            and event.clock == clock
            and not (
                hasattr(event, "is_first_ft")
                and not event.is_technical_ft
                and self.team_id != event.team_id
            )
        ):
            event = event.next_event

        if (
            event is not None
            and hasattr(event, "is_first_ft")
            and not event.is_technical_ft
            and event.clock == clock
            and (not hasattr(self, "player3_id") or self.player3_id == event.player1_id)
        ):
            # player3 id check is to make sure player who got fouled is player shooting free throws, prior to 2005-06 because foul drawning player isn't in pbp
            if "of 1" in event.description:
                return 1
            elif "of 2" in event.description:
                return 2
            elif "of 3" in event.description:
                return 3

        # if we haven't found ft yet, try going backwards
        event = self
        while (
            event is not None
            and event.clock == clock
            and not (
                hasattr(event, "is_first_ft")
                and not event.is_technical_ft
                and self.team_id != event.team_id
            )
        ):
            event = event.previous_event

        if (
            event is not None
            and hasattr(event, "is_first_ft")
            and not event.is_technical_ft
            and event.clock == clock
            and (not hasattr(self, "player3_id") or self.player3_id == event.player1_id)
        ):
            # player3 id check is to make sure player who got fouled is player shooting free throws, prior to 2005-06 because foul drawning player isn't in pbp
            if "of 1" in event.description:
                return 1
            elif "of 2" in event.description:
                return 2
            elif "of 3" in event.description:
                return 3
        return None

    @property
    def is_personal_foul(self):
        return self.sub_type == "Personal"

    @property
    def is_shooting_foul(self):
        return self.sub_type == "Shooting"

    @property
    def is_loose_ball_foul(self):
        return self.sub_type == "Loose Ball"

    @property
    def is_offensive_foul(self):
        return self.sub_type == "Offensive"

    @property
    def is_inbound_foul(self):
        return self.sub_type == "Inbound"

    @property
    def is_away_from_play_foul(self):
        return self.sub_type == "Away From Play"

    @property
    def is_clear_path_foul(self):
        return self.sub_type == "Clear Path"

    @property
    def is_double_foul(self):
        return self.sub_type == "Double Personal"

    @property
    def is_technical(self):
        return self.sub_type in [
            "Technical",
            "Non-Unsportsmanlike Technical",
            "Hanging Technical",
            "Delay Technical",
            "Excess Timeout Technical",
            "Too Many Players Technical",
        ]

    @property
    def is_flagrant1(self):
        return self.sub_type == "Flagrant Type 1"

    @property
    def is_flagrant2(self):
        return self.sub_type == "Flagrant Type 2"

    @property
    def is_double_technical(self):
        return self.sub_type == "Double Technical"

    @property
    def is_defensive_3_seconds(self):
        return self.sub_type == "Defense 3 Second"

    @property
    def is_delay_of_game(self):
        return self.sub_type == "Delay Technical"

    @property
    def is_charge(self):
        return self.sub_type == "Offensive Charge"

    @property
    def is_personal_block_foul(self):
        return self.sub_type == "Personal Block"

    @property
    def is_personal_take_foul(self):
        return self.sub_type == "Personal Take"

    @property
    def is_shooting_block_foul(self):
        return self.sub_type == "Shooting Block"

    @property
    def is_transition_take_foul(self):
        return self.sub_type == "Transition Take"
