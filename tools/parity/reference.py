"""Materialize and verify the original from Git without importing the candidate."""

import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "e7ccf2fb6326da630a3cf1665aac964a1e108f4c"


def git(*args):
    return subprocess.check_output(
        ["git", "-c", "safe.directory=" + ROOT.as_posix(), "-C", str(ROOT), *args]
    )


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prepare_reference(name="reference"):
    manifest = json.loads(
        (ROOT / "tests/parity/manifest.json").read_text(encoding="utf-8")
    )
    revision = manifest[name + "_revision"]
    archive = git("archive", "--format=zip", revision)
    if digest(archive) != manifest[name + "_archive_sha256"]:
        raise ValueError("Pinned reference archive hash changed")
    target = ROOT / ".parity" / (name + "-" + revision[:7])
    if not target.exists():
        target.mkdir(parents=True)
        with zipfile.ZipFile(io.BytesIO(archive)) as source:
            for member in source.infolist():
                path = (target / member.filename).resolve()
                if target.resolve() not in path.parents and path != target.resolve():
                    raise ValueError("Reference archive path escapes target")
            source.extractall(target)
    for filename, expected in manifest[name + "_files"].items():
        if digest((target / filename).read_bytes()) != expected:
            raise ValueError("Reference modified: " + filename)
    actual_files = {
        p.relative_to(target).as_posix() for p in (target / "pbpstats").rglob("*.py")
    }
    expected_files = {
        p
        for p in manifest[name + "_files"]
        if p.startswith("pbpstats/") and p.endswith(".py")
    }
    if actual_files != expected_files:
        raise ValueError("Reference Python source inventory changed")
    return target
