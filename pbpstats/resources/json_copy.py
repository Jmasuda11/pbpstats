"""Copy decoded JSON without ``copy.deepcopy``'s general-purpose overhead."""


def json_copy(value):
    """Return an independent copy of a structure decoded from JSON.

    ``copy.deepcopy`` carries a memo table and dispatches through
    ``__reduce_ex__`` for values that JSON can never produce. Decoded JSON is
    only dicts, lists and immutable scalars, so recursing over those three
    cases gives the same isolation several times faster.

    :param value: dicts, lists and immutable scalars, as ``json`` returns them
    """
    if isinstance(value, dict):
        return {key: json_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_copy(item) for item in value]
    return value
