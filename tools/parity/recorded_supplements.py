"""Independent recorded facts for research context, never prior parser outputs."""

import json
from pathlib import Path

from tools.parity.participant_names import actor_alias, add_actor_aliases
from tools.parity.reference import ROOT, digest


ALIAS_MANIFEST = "tests/parity/participant-alias-evidence.json"


def evidence_hashes():
    manifest = ROOT / ALIAS_MANIFEST
    data = manifest.read_bytes()
    result = {ALIAS_MANIFEST: digest(data)}
    for item in json.loads(data)["observations"]:
        path = (ROOT / item["path"]).resolve()
        if ROOT.resolve() not in path.parents:
            raise ValueError("Alias source escapes research checkout")
        result[item["path"]] = digest(path.read_bytes())
    return result


def add_recorded_aliases(game_id, roster, require):
    manifest_bytes = (ROOT / ALIAS_MANIFEST).read_bytes()
    manifest = json.loads(manifest_bytes)
    require(manifest.get("schema_version") == 1, "alias_evidence", "Invalid alias evidence schema")
    witnesses = []
    for item in manifest["observations"]:
        if not game_id.startswith(item["season_id_prefix"]):
            continue
        identity, team = item["row"]["personId"], item["row"]["teamId"]
        if identity not in roster or roster[identity]["team_id"] != team:
            continue
        path = (ROOT / item["path"]).resolve()
        require(ROOT.resolve() in path.parents, "alias_evidence", "Alias source escapes research checkout")
        raw = path.read_bytes()
        require(digest(raw) == item["sha256"], "alias_evidence", "Alias source hash changed")
        game = json.loads(raw)["game"]
        require(
            game["gameId"] == item["source_game_id"]
            and game["gameId"].startswith(item["season_id_prefix"])
            and game["actions"][item["source_index"]] == item["row"]
            and actor_alias(item["row"]) is not None,
            "alias_evidence", "Alias observation disagrees with pinned source",
        )
        for witness in add_actor_aliases([item["row"]], roster, require):
            witness.update(
                source_index=item["source_index"], source_game_id=game["gameId"],
                path=item["path"], sha256=item["sha256"],
                manifest_sha256=digest(manifest_bytes),
                basis="same_season_team_and_player_id_bound_actor_description",
            )
            witnesses.append(witness)
    return witnesses


def live_foul_drawn_witnesses(game_id, files, rows, roster, require):
    """Match explicit personal-foul roles at the same action, period and clock.

    This supplies on-court evidence only. It neither alters native events nor
    enables foul-drawn statistics. Other live families need their own contract.
    """
    path = "bundle/pbp/live_{}.json".format(game_id)
    if path not in files:
        return {}
    raw = files[path]
    game = json.loads(raw)["game"]
    require(game.get("gameId") == game_id, "live_evidence", "Live game identity disagrees")
    actions = {}
    for index, row in enumerate(game["actions"]):
        actions.setdefault(row.get("actionNumber"), []).append((index, row))
    result = {}
    for index, row in enumerate(rows):
        if (row["actionType"], row["subType"]) != ("Foul", "Personal"):
            continue
        matches = actions.get(row["actionNumber"], [])
        if not matches:
            continue
        require(len(matches) == 1, "live_evidence", "Ambiguous live action identity", source_index=index)
        live_index, live = matches[0]
        require(
            all(live.get(k) == row[k] for k in ("period", "clock", "personId", "teamId"))
            and (live.get("actionType"), live.get("subType")) == ("foul", "personal")
            and not live.get("descriptor"),
            "live_evidence", "Live personal foul contradicts native action", source_index=index,
        )
        player = live.get("foulDrawnPersonId")
        if player in (None, 0):
            continue
        require(
            type(player) is int and player in roster
            and row["personId"] in roster
            and roster[player]["team_id"] != roster[row["personId"]]["team_id"],
            "live_evidence", "Live foul-drawn player must belong to opposing roster", source_index=index,
        )
        result[index] = dict(
            source_index=index, action_number=row["actionNumber"], player_id=player,
            role="live_foul_drawn", path=path, sha256=digest(raw),
            live_source_index=live_index, basis="explicit_live_role_on_matching_native_action",
        )
    return result
