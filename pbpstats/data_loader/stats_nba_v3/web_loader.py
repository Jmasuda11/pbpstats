import os
from pathlib import Path

import requests

from pbpstats import REQUEST_TIMEOUT
from pbpstats.data_loader.stats_nba_v3.base import StatsNbaV3LoaderBase
from pbpstats.data_loader.stats_nba_v3.decoder import V3DecodeError

# The original's own league hosts, keyed by game ID prefix.
STATS_URLS = {"00": "https://stats.nba.com/stats/", "10": "https://stats.wnba.com/stats/"}
# The stats API rejects pbpstats' older default headers; these follow nba_api.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Referer": "https://www.nba.com/",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
    "Sec-Ch-Ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Fetch-Dest": "empty",
}


def get(url, params, session=None):
    """One stats.nba.com request; the caller decides how to treat its status."""
    return (session or requests).get(
        url, params=sorted(params.items()), headers=HEADERS, timeout=REQUEST_TIMEOUT
    )


def stats_url(game_id):
    """Stats API base URL for a supported league; nothing is requested otherwise."""
    if not isinstance(game_id, str) or game_id[:2] not in STATS_URLS:
        raise V3DecodeError("Only NBA and WNBA game IDs are supported")
    return STATS_URLS[game_id[:2]]


def save_response(file_directory, file_path, content):
    """Keep a response's exact bytes on disk when a data directory is given."""
    if file_directory is not None and os.path.isdir(file_directory):
        Path(file_path).write_bytes(content)


class StatsNbaV3WebLoader(StatsNbaV3LoaderBase):
    """
    Base class for loading data from stats.nba.com V3 API requests.

    The response is kept as its exact bytes, which reviewed corrections and
    recorded evidence are bound to.

    This class should not be instantiated directly.
    """

    def _load_request_data(self):
        response = get(self.base_url, self.parameters)
        response.raise_for_status()
        self.source = response.url
        self.source_data = response.content
        save_response(self.file_directory, self.file_path, self.source_data)
        return self.source_data
