"""Collect names only where a recorded description names its explicit actor."""

import re
import unicodedata

from .decoder import V3DecodeError


def require(condition, code, message, **details):
    """Default evidence check: an unsupported name fact is a decode rejection."""
    if not condition:
        raise V3DecodeError(message)


def unaccented(name):
    return "".join(
        c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c)
    )


def actor_alias(row):
    """Return (name, role) for bounded, unambiguous actor-description grammars.

    Incoming substitutes, assisters, opponents and tip recipients are deliberately
    excluded: their identity is not the row's personId. No player-name heuristics
    or previous parser output participate in this extraction.
    """
    kind, subtype, description = (
        row.get("actionType"),
        row.get("subType"),
        row.get("description"),
    )
    if not isinstance(description, str):
        return None
    if kind == "Substitution" and subtype == "":
        match = re.fullmatch(r"SUB: [^()]+ FOR ([^()]+)", description)
        role = "outgoing"
    elif kind == "Rebound" and subtype in ("Unknown", "Normal Rebound"):
        match = re.fullmatch(r"([^()]+?) REBOUND \(Off:\d+ Def:\d+\)", description)
        role = "rebounder"
    elif kind == "" and subtype == "":
        match = re.fullmatch(
            r"([^()]+?) (?:STEAL \(\d+ STL\)|BLOCK \(\d+ BLK\))", description
        )
        role = "secondary_actor"
    elif kind == "Free Throw" and re.fullmatch(
        r"Free Throw(?: (?:Technical|Clear Path|Flagrant))?(?: [1-3] of [1-3])?",
        subtype or "",
    ):
        match = re.fullmatch(
            r"(?:MISS )?([^()]+?) " + re.escape(subtype) + r"(?: \(\d+ PTS\))?",
            description,
        )
        role = "free_throw_shooter"
    else:
        return None
    return (match[1].strip(), role) if match else None


def add_unaccented_names(roster):
    """Descriptions often omit accents; keep both spellings so collisions show."""
    for facts in roster.values():
        for name in list(facts["names"]):
            plain = unaccented(name)
            if plain not in facts["names"]:
                facts["names"].append(plain)


def roster_from_actors(rows, teams, require=require):
    """Players who act in these V3 rows, named only by their own rows.

    Team and replay identities and teamless people (coaches) are skipped.
    Names come from each actor's playerName/playerNameI, ID-bound actor
    descriptions and unaccented variants; nobody is inferred from a name.
    """
    roster = {}
    for row in rows:
        identity, team = row["personId"], row["teamId"]
        if not identity or identity in teams or team not in teams:
            continue
        facts = roster.setdefault(identity, {"team_id": team, "names": []})
        require(facts["team_id"] == team, "roster_identity", "Actor changes team")
        for name in (row["playerName"], row["playerNameI"]):
            if name.strip() and name not in facts["names"]:
                facts["names"].append(name)
    add_actor_aliases(rows, roster, require)
    add_unaccented_names(roster)
    return {identity: facts for identity, facts in roster.items() if facts["names"]}


def add_actor_aliases(rows, roster, require=require):
    """Augment roster names and retain the exact witness for every new alias."""
    known = {}
    for identity, facts in roster.items():
        for name in facts["names"]:
            known.setdefault(
                (facts["team_id"], unaccented(name).casefold()), set()
            ).add(identity)
    witnesses = []
    for index, row in enumerate(rows):
        identity = row.get("personId")
        alias = actor_alias(row)
        if identity not in roster or alias is None:
            continue
        name, role = alias
        team = roster[identity]["team_id"]
        key = (team, unaccented(name).casefold())
        # A description cannot rename a different explicitly identified player.
        # Retain existing collisions; never pick a winner between shared names.
        require(
            key not in known or identity in known[key],
            (
                "substitution_evidence"
                if role == "outgoing"
                else "participant_alias_conflict"
            ),
            "Actor description contradicts an ID-bound roster name",
            source_index=index,
            player_id=identity,
            name=name,
            candidates=sorted(known.get(key, ())),
        )
        if name not in roster[identity]["names"]:
            roster[identity]["names"].append(name)
            witnesses.append(
                dict(
                    source_index=index,
                    action_number=row["actionNumber"],
                    player_id=identity,
                    team_id=team,
                    name=name,
                    role=role,
                )
            )
        known.setdefault(key, set()).add(identity)
    return witnesses
