"""
``StatsEnhancedPbpItem`` is the base class for all stats.nba.com enhanced pbp event types
"""
from collections import defaultdict

import requests

from pbpstats import HEADERS, REQUEST_TIMEOUT
from pbpstats.resources.enhanced_pbp.enhanced_pbp_item import EnhancedPbpItem
from pbpstats.resources.enhanced_pbp.possession_rules import PossessionRules

KEY_ATTR_MAPPER = {
    "GAME_ID": "game_id",
    "EVENTNUM": "event_num",
    "PCTIMESTRING": "clock",
    "PERIOD": "period",
    "EVENTMSGACTIONTYPE": "event_action_type",
    "EVENTMSGTYPE": "event_type",
    "PLAYER1_ID": "player1_id",
    "PLAYER1_TEAM_ID": "team_id",
    "PLAYER2_ID": "player2_id",
    "PLAYER3_ID": "player3_id",
    "VIDEO_AVAILABLE_FLAG": "video_available",
}


class StatsEnhancedPbpItem(PossessionRules, EnhancedPbpItem):
    """
    Base class for enhanced pbp events from stats.nba.com

    :param dict event: dict with event data
    :param int order: sequential order in which event occurs
    """

    def __init__(self, event, order):
        # set unconditionally so a missing or null GAME_ID is None rather than
        # an undefined attribute, matching LiveEnhancedPbpItem/DataEnhancedPbpItem
        self.game_id = event.get("GAME_ID")
        for key, value in KEY_ATTR_MAPPER.items():
            if event.get(key) is not None:
                setattr(self, value, event.get(key))

        if (
            event.get("HOMEDESCRIPTION") is not None
            and event.get("VISITORDESCRIPTION") is not None
        ):
            self.description = (
                f"{event.get('HOMEDESCRIPTION')}: {event.get('VISITORDESCRIPTION')}"
            )
        elif event.get("HOMEDESCRIPTION") is not None:
            self.description = f"{event.get('HOMEDESCRIPTION')}"
        elif event.get("VISITORDESCRIPTION") is not None:
            self.description = f"{event.get('VISITORDESCRIPTION')}"
        elif event.get("NEUTRALDESCRIPTION") is not None:
            self.description = f"{event.get('NEUTRALDESCRIPTION')}"
        else:
            self.description = ""

        if (
            event.get("PLAYER1_TEAM_ID") is None
            and event.get("PLAYER1_ID") is not None
            and event.get("EVENTMSGTYPE") != 18
        ):
            # need to set team id in these cases where player id is team id
            # EVENTMSGTYPE 18 is replay event - it is ignored because it has no team id and unknown player id
            self.team_id = event.get("PLAYER1_ID", 0)
            self.player1_id = 0

        # fix team/player ids on some event types so they are consistent with DataPbpItem
        if self.event_type == 10:
            # jump ball PLAYER3_TEAM_ID is player who ball gets tipped to
            self.player2_id = event["PLAYER3_ID"]
            self.player3_id = event["PLAYER2_ID"]
            if event["PLAYER3_TEAM_ID"] is not None:
                self.team_id = event["PLAYER3_TEAM_ID"]
            else:
                # when jump ball is tipped out of bounds, winning team is PLAYER3_ID
                self.team_id = event["PLAYER3_ID"]
                if hasattr(self, "player2_id"):
                    delattr(self, "player2_id")
        elif self.event_type in [5, 6]:
            # steals need to change PLAYER2_ID to player3_id - this is player who turned ball over
            # fouls need to change PLAYER2_ID to player3_id - this is player who drew foul
            if hasattr(self, "player2_id"):
                delattr(self, "player2_id")
            if event.get("PLAYER2_ID") is not None:
                self.player3_id = event["PLAYER2_ID"]

        if hasattr(self, "player2_id") and self.player2_id == 0:
            delattr(self, "player2_id")
        if hasattr(self, "player3_id") and self.player3_id == 0:
            delattr(self, "player3_id")
        self.order = order
        self.player_game_fouls = defaultdict(int)
        self.possession_changing_override = False
        self.non_possession_changing_override = False
        self.score = defaultdict(int)

    @property
    def data(self):
        """
        returns event as a dict
        """
        return self.__dict__

    @property
    def seconds_remaining(self):
        """
        returns seconds remaining in period as a ``float``
        """
        split = self.clock.split(":")
        return float(split[0]) * 60 + float(split[1])

    @property
    def video_url(self):
        """
        returns url for mp4 video of play, if available
        """
        if self.video_available == 1:
            parameters = {"GameEventID": self.event_num, "GameID": self.game_id}
            base_url = "https://stats.nba.com/stats/videoeventsasset"
            response = requests.get(
                base_url, parameters, headers=HEADERS, timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                response_json = response.json()
                video_urls = response_json["resultSets"]["Meta"]["videoUrls"]
                if len(video_urls) == 1:
                    return video_urls[0]["murl"]
            else:
                response.raise_for_status()
        return None
