"""Associate source rows without discarding them or repairing their order."""

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional, Tuple

from pbpstats.resources.pbp.stats_nba_v3_pbp_item import StatsNbaV3PbpItem


@dataclass(frozen=True)
class V3EventGroup:
    primary: StatsNbaV3PbpItem
    rows: Tuple[StatsNbaV3PbpItem, ...]
    steal: Optional[StatsNbaV3PbpItem] = None
    block: Optional[StatsNbaV3PbpItem] = None

    @property
    def source_indices(self):
        return tuple(row.order for row in self.rows)


def _error(rows, message):
    indices = tuple(row.order for row in rows)
    return ValueError(
        f"Stats V3 game {rows[0].game_id}, source rows {indices}: {message}"
    )


def _make_group(rows):
    primary = [row for row in rows if row.action_type]
    if len(primary) != 1:
        raise _error(rows, "expected exactly one typed primary action")
    if len({(row.period, row.seconds_remaining_exact) for row in rows}) != 1:
        raise _error(rows, "action number has conflicting periods or clocks")
    secondary = {}
    for row in rows:
        if row is primary[0]:
            continue
        description = row.data["description"]
        if re.fullmatch(r".+ STEAL \([0-9]+ STL\)", description):
            role, expected_type = "steal", "Turnover"
        elif re.fullmatch(r".+ BLOCK \([0-9]+ BLK\)", description):
            role, expected_type = "block", "Missed Shot"
        else:
            raise _error(rows, "unrecognized blank-type secondary action")
        blocked_heave = role == "block" and (
            primary[0].action_type, primary[0].sub_type
        ) == ("Heave", "Team Field Goal Attempt")
        if primary[0].action_type != expected_type and not blocked_heave:
            raise _error(rows, f"{role} requires a {expected_type} primary action")
        if role in secondary:
            raise _error(rows, f"multiple {role} rows are ambiguous")
        secondary[role] = row
    return V3EventGroup(primary[0], tuple(rows), **secondary)


def associate_actions(items):
    """Return groups in primary source order; reject ambiguous associations.

    Action numbers are association candidates within one snapshot, not stable
    identifiers. Repeated rows remain intact in the raw loader; this layer
    rejects duplicate primary/secondary identities instead of choosing a row.
    """
    items = tuple(items)
    if not items:
        return ()
    if any(not isinstance(item, StatsNbaV3PbpItem) for item in items):
        raise TypeError("associate_actions requires StatsNbaV3PbpItem objects")
    if len({item.game_id for item in items}) != 1:
        raise _error(items, "cannot associate actions from different games")
    if any(a.order >= b.order for a, b in zip(items, items[1:])):
        raise _error(items, "actions must retain increasing source positions")
    seen_ids = {}
    candidates = defaultdict(list)
    for item in items:
        if item.action_id in seen_ids:
            raise _error(
                (seen_ids[item.action_id], item),
                "repeated actionId in the same snapshot",
            )
        seen_ids[item.action_id] = item
        candidates[item.action_number].append(item)
    groups = [_make_group(rows) for rows in candidates.values()]
    return tuple(sorted(groups, key=lambda group: group.primary.order))
