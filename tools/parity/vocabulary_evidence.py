"""Read exact observations from pinned JSON recordings and V2 CSV exports."""

import csv
from functools import lru_cache
import io
import json
import tarfile

from tools.parity.reference import ROOT, digest, prepare_reference


def free_throw_vocabulary():
    return json.loads((ROOT / "tests/parity/free-throw-vocabulary.json").read_bytes())


@lru_cache(maxsize=1)
def observed_rows():
    """Stream the full archive once; retain only explicitly cited source rows."""
    shot = json.loads((ROOT / "tests/parity/shot-vocabulary.json").read_bytes())
    mappings = shot["mappings"] + free_throw_vocabulary()["mappings"]
    observations = [m[v] for m in mappings for v in ("v2", "v3")]
    observations += [m["v2"] for m in shot.get("unresolved_aliases", [])]
    roots = {"reference": prepare_reference(), "prior": prepare_reference("prior")}
    for name, source in shot["external_recordings"].items():
        raw = (ROOT / source["path"]).read_bytes()
        assert digest(raw) == source["sha256"]
        assert len(raw) == source["bytes"]
        for path, expected in source.get("provenance_files", {}).items():
            assert digest((ROOT / path).read_bytes()) == expected
        roots[name] = ROOT

    groups = {}
    for observation in observations:
        key = (observation["reference"], observation["path"])
        groups.setdefault(key, []).append(observation)
    result = {}
    for (reference, path), selected in groups.items():
        raw = (roots[reference] / path).read_bytes()
        actual_hash = digest(raw)
        assert all(actual_hash == o["sha256"] for o in selected)
        indices = {o["source_index"] for o in selected}
        if selected[0].get("format") == "v2-csv-tar-xz":
            source = shot["external_recordings"][reference]
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as archive:
                # Read the named member in memory; never extract archive paths.
                csv_bytes = archive.extractfile(source["member"]).read()
            assert digest(csv_bytes) == source["member_sha256"]
            rows = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig")))
        else:
            payload = json.loads(raw)
            if "game" in payload:
                rows = payload["game"]["actions"]
            else:
                table = payload["resultSets"][0]
                rows = (dict(zip(table["headers"], r)) for r in table["rowSet"])
        for index, row in enumerate(rows):
            if index in indices:
                result[reference, path, index] = row
    return result


def assert_observation(observation):
    key = (observation["reference"], observation["path"], observation["source_index"])
    assert observed_rows()[key] == observation["row"]
