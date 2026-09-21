"""League/season rules for native V3 validation, separate from feed vocabulary."""

import re
from dataclasses import dataclass

LEAGUES = {"00": "NBA", "10": "WNBA", "20": "G League"}
GAME_ID_PATTERN = re.compile(r"(?:00|10|20)[0-9]{8}")


def validate_game_id(game_id, league_id=None):
    if not isinstance(game_id, str) or not GAME_ID_PATTERN.fullmatch(game_id):
        raise ValueError(
            "Stats V3 game_id must be a 10-digit NBA, WNBA, or G League string starting with 00, 10, or 20"
        )
    if league_id is not None and (
        not isinstance(league_id, str) or league_id not in LEAGUES
    ):
        raise ValueError(
            "league_id must be '00' (NBA), '10' (WNBA), or '20' (G League)"
        )
    if league_id is not None and game_id[:2] != league_id:
        raise ValueError("league_id conflicts with game_id prefix")
    return game_id[:2]


@dataclass(frozen=True)
class V3LeagueRules:
    league_id: str
    season_start_year: int

    def __post_init__(self):
        if not isinstance(self.league_id, str) or self.league_id not in LEAGUES:
            raise ValueError("unknown V3 league_id")
        if (
            type(self.season_start_year) is not int
            or not 1970 <= self.season_start_year <= 2069
        ):
            raise ValueError(
                "season_start_year must be an integer from 1970 through 2069"
            )
        if self.league_id == "10" and self.season_start_year < 2006:
            raise ValueError(
                "V3 WNBA validation requires the four-quarter format (2006 or later)"
            )

    @classmethod
    def for_game(cls, game_id, league_id=None):
        league = validate_game_id(game_id, league_id)
        if game_id[2] not in ("2", "4"):
            raise ValueError(
                "V3 league rules currently support regular-season and playoff game IDs only"
            )
        year = int(game_id[3:5])
        return cls(league, 2000 + year if year < 70 else 1900 + year)

    @property
    def name(self):
        return LEAGUES[self.league_id]

    @property
    def regulation_seconds(self):
        return 600 if self.league_id == "10" else 720

    def untimed(self, period):
        return self.league_id == "20" and self.season_start_year >= 2022 and period > 4

    def opening_clock(self, period):
        # The recorded G League feed measures elapsed OT using a 99:00 counter;
        # this is not a 99-minute period or a time-based ending condition.
        if self.untimed(period):
            return 99 * 60
        return self.regulation_seconds if period <= 4 else 300

    def single_free_throw(self, period, seconds):
        return (
            self.league_id == "20"
            and self.season_start_year >= 2019
            and period <= 4
            and not (period == 4 and seconds <= 120)
        )

    def fouls_to_give(self, period):
        return 4 if period <= 4 else 3

    def last_two_minutes(self, period, seconds):
        return not self.untimed(period) and seconds <= 120

    def transition_take(self, period, seconds):
        if self.league_id == "20" and period > 4:
            return False
        return not (period >= 4 and seconds <= 120)

    def team_heave(self, period, seconds):
        available = (self.league_id == "00" and self.season_start_year >= 2025) or (
            self.league_id == "20" and self.season_start_year >= 2024
        )
        return available and period <= 3 and seconds <= 3
