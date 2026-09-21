"""Shared access to the recorded V3 fixtures and their manifest.

``manifest.json`` is the single inventory, so every module that reads a
fixture goes through here rather than re-deriving the path or re-parsing the
manifest.
"""
import functools
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"


@functools.lru_cache(maxsize=None)
def load_json(relative_path):
    """Cached: callers only read the returned objects, never mutate them."""
    return json.loads((DATA / relative_path).read_text(encoding="utf-8"))


def actions(game_id):
    return load_json(f"pbp/stats_v3_{game_id}.json")["game"]["actions"]


def manifest_fixtures():
    return load_json("v3/manifest.json")["fixtures"]
