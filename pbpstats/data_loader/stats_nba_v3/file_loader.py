from pathlib import Path

from pbpstats.data_loader.stats_nba_v3.base import StatsNbaV3LoaderBase


class SavedResponse:
    """A recorded response read back from disk, with the request URL it answered."""

    status_code, reason = 200, "OK"

    def __init__(self, content, url):
        self.content, self.url = content, url


class StatsNbaV3FileLoader(StatsNbaV3LoaderBase):
    """
    Base class for loading stats.nba.com V3 files saved on disk.

    A file is read as the exact response bytes, which reviewed corrections and
    recorded evidence are bound to.

    This class should not be instantiated directly.
    """

    def _load_data_from_file(self):
        data_file = Path(self.file_path)
        if not data_file.is_file():
            raise Exception(f"{self.file_path} does not exist")
        self.source = self.file_path
        self.source_data = data_file.read_bytes()
        return self.source_data
