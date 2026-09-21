"""Offline traditional V3 box-score evidence and game context."""

from .file import StatsNbaV3BoxscoreFileLoader
from .loader import StatsNbaV3BoxscoreLoader, V3BoxscoreSourceData

__all__ = [
    "StatsNbaV3BoxscoreFileLoader",
    "StatsNbaV3BoxscoreLoader",
    "V3BoxscoreSourceData",
]
