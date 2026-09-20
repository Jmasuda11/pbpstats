Loading recorded Stats V3 actions
=================================

The native V3 file loader reads recorded NBA PlayByPlayV3 responses. It exposes
validated raw actions with their original fields and order. It does not resolve
participants, repair event sequences, infer lineups, or calculate possessions.

Usage
-----

Save the response as ``pbp/stats_v3_<game_id>.json`` below your data directory.
The V3 filename is separate from the existing V2 cache. No network request or
fallback to a different provider occurs, and the input file is never rewritten.

.. code-block:: python

    from pbpstats.data_loader.stats_nba_v3.pbp import (
        StatsNbaV3PbpFileLoader,
        StatsNbaV3PbpLoader,
    )

    source = StatsNbaV3PbpFileLoader("tests/data")
    pbp = StatsNbaV3PbpLoader("0021900001", source)

    first_action = pbp.items[0]
    print(first_action.order)              # zero-based source array index
    print(first_action.action_id)          # original actionId
    print(first_action.action_number)      # original actionNumber
    print(first_action.clock)              # original ISO-style clock
    print(first_action.seconds_remaining)  # Decimal, retaining fractional seconds
    print(first_action.data)               # original action fields

Import these classes directly from the module shown above. This file-only
provider is not registered with ``Client`` or the existing loader factory, which
currently requires both file and web implementations. Existing providers keep
their existing registration and behavior.

Preserved data
--------------

``pbp.source_bytes`` contains the exact file contents, including whitespace and
encoding markers. ``pbp.source_data`` returns the complete decoded JSON envelope,
and ``pbp.data`` returns its action list. These dictionaries and lists are
defensive copies; changing them or an item's ``data`` does not alter the stored
source. Derived attributes such as ``order`` are never inserted into raw actions.
Unknown envelope, game, and action fields remain available.

Every source action produces one item. Identical rows and repeated identifiers
are retained. In particular, blank-type steal and block rows are not discarded
or merged. Unrecognized event types remain raw actions for later interpretation.
Neither NBA identifier is assumed to be a stable key across corrected snapshots.

``order`` always identifies the action's original array position. ``action_id``,
``action_number``, ``action_type``, ``sub_type``, ``period``, and ``clock`` expose
their corresponding source fields as read-only properties. ``game_id`` comes
from the validated response identity. Numeric clocks use ``Decimal`` independently
of the caller's decimal precision. Other JSON numbers use normal Python integer
and float decoding; their exact original spelling is retained in ``source_bytes``.

Validation and limits
---------------------

Game IDs must be ten ASCII digits beginning with ``00``; this initial provider
supports NBA records. The response must contain a ``game`` object with a matching
``gameId`` and an ``actions`` array. Each action must provide integer
``actionId`` and ``actionNumber`` values greater than or equal to zero, a positive
integer ``period``, and string ``actionType``, ``subType``, ``description``, and
``clock`` values. Empty type and description strings remain valid recorded data.

Clocks must use ``PT<minutes>M<seconds>S`` with optional fractional seconds.
Seconds must be less than 60, and the total must fit a 12-minute regulation
period or a 5-minute overtime period. No integer truncation is applied.

Missing files raise ``FileNotFoundError``. Invalid JSON or unsupported structure
raises ``ValueError`` with game context; action validation also includes the
source array index and field. Duplicate JSON keys, non-finite numbers, and numbers
that overflow Python float decoding are rejected rather than silently replaced.
UTF-8 files with or without a byte-order mark are accepted.

An empty action array and a partial excerpt can be read as raw data. A successful
load does **not** establish that the game is complete or its basketball semantics
are valid. Completion, participant resolution, and statistical completeness need
additional validation before a future enhanced-event or possession loader may
use these records. The eight-action heave fixture remains an incomplete excerpt.
