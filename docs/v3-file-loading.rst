Loading recorded Stats V3 actions
=================================

The native V3 file loader reads recorded NBA, WNBA, and G League PlayByPlayV3 responses. It exposes
validated raw actions with their original fields and order. It does not resolve
participants, repair event sequences, infer lineups, or calculate possessions.
The separate :doc:`v3-participants` layer associates rows and records participant
identities using explicit game context.
See :doc:`v3-leagues` for league parameters, clock rules, and recent fixtures.

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
    print(first_action.description)        # original description
    print(first_action.seconds_remaining)  # float, matching other providers
    print(first_action.seconds_remaining_exact)  # Decimal, keeping the scale
    print(first_action.get("personId"))    # one field, without copying the action
    print(first_action.data)               # original action fields

The provider is registered as ``stats_nba_v3``, so ``Client`` can load it from
file like any other. It has no web loader; asking for ``source: "web"`` raises
a ``ValueError`` naming the missing source. Existing providers keep their
existing registration and behavior.

.. code-block:: python

    from pbpstats.client import Client

    settings = {
        "dir": "tests/data",
        "Pbp": {"source": "file", "data_provider": "stats_nba_v3"},
    }
    game = Client(settings).Game("0021900001")

Preserved data
--------------

``pbp.source_bytes`` contains the exact file contents, including whitespace and
encoding markers. The source loader returns those bytes together with the payload
it decoded them from, so one source loader can serve several games without a
loader ever receiving another game's bytes. ``pbp.source_data`` returns the
complete decoded JSON envelope, and ``pbp.data`` returns its action list. These
dictionaries and lists are defensive copies; changing them or an item's ``data``
does not alter the stored source. Derived attributes such as ``order`` are never
inserted into raw actions. Unknown envelope, game, and action fields remain
available.

Each of ``source_data``, ``data``, and an item's ``data`` builds its copy on
every read. Bind one to a local rather than indexing it in a loop, and read a
single field with ``item.get(field)``, which copies nothing for a scalar.

Every source action produces one item. Identical rows and repeated identifiers
are retained. In particular, blank-type steal and block rows are not discarded
or merged. Unrecognized event types remain raw actions for later interpretation.
Neither NBA identifier is assumed to be a stable key across corrected snapshots.

``order`` always identifies the action's original array position. ``action_id``,
``action_number``, ``action_type``, ``sub_type``, ``description``, ``period``,
and ``clock`` expose their corresponding source fields as read-only properties;
``get`` reaches any other recorded field. ``game_id`` comes from the validated
response identity.

``seconds_remaining`` is a ``float``, the type the shared enhanced-event
interface uses, so V3 items mix with other providers' events in shared
arithmetic. ``seconds_remaining_exact`` is the ``Decimal`` the clock was parsed
to, retaining the recorded scale; keep it out of shared arithmetic, where mixing
``Decimal`` with ``float`` raises ``TypeError``. Both are computed in an isolated
decimal context, so the caller's precision, rounding, exponent limits and traps
cannot round or reject a recorded clock. Other JSON numbers use normal Python
integer and float decoding; their exact original spelling is retained in
``source_bytes``.

Validation and limits
---------------------

Game IDs must be ten ASCII digits beginning with ``00``, ``10``, or ``20``;
league rules currently cover regular-season and playoff formats. The
response must contain a ``game`` object with a matching ``gameId`` and an
``actions`` array. Each action must provide integer
``actionId`` and ``actionNumber`` values greater than or equal to zero, a positive
integer ``period``, and string ``actionType``, ``subType``, ``description``, and
``clock`` values. Empty type and description strings remain valid recorded data.

Clocks must use ``PT<minutes>M<seconds>S`` with optional fractional seconds.
Seconds must be less than 60, and the total must fit the league's regulation
or overtime clock, including the G League's untimed-OT counter convention
described in :doc:`v3-leagues`. No integer truncation is applied.

A missing or blank ``file_directory`` raises ``ValueError`` when the source
loader is constructed, rather than silently resolving to the working directory.
Missing files raise ``FileNotFoundError``. Invalid JSON or unsupported structure
raises ``ValueError`` with game context; action validation also includes the
source array index and field. That includes JSON nested too deeply for the
decoder, which would otherwise escape as ``RecursionError``, so catching
``ValueError`` is enough to skip one unreadable file. Duplicate JSON keys,
non-finite numbers, and numbers that overflow Python float decoding are rejected
rather than silently replaced. UTF-8 files with or without a byte-order mark are
accepted.

A source loader must return a ``V3PbpSourceData`` carrying the payload and the
bytes it came from. Anything else raises ``TypeError`` instead of leaving
``source_bytes`` quietly unset.

An empty action array and a partial excerpt can be read as raw data. A successful
load does **not** establish that the game is complete or its basketball semantics
are valid. Completion, participant resolution, and statistical completeness need
additional validation before a future enhanced-event or possession loader may
use these records. The eight-action heave fixture remains an incomplete excerpt.
