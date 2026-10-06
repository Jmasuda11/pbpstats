"""Record original failures; fail if their identities or causes change."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from tools.parity.reference import ROOT, prepare_reference


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate",
        type=Path,
        help="Run the untouched original tests against this package",
    )
    args = parser.parse_args()
    reference = prepare_reference()
    output = (
        ROOT
        / ".parity"
        / ("candidate-legacy-tests" if args.candidate else "baseline-tests")
    )
    output.mkdir(parents=True, exist_ok=True)
    expected = {
        "tests.resources.test_free_throw.test_away_from_play_free_throw_type",
        "tests.resources.test_free_throw.test_flagrant_free_throw_type",
    }
    with tempfile.TemporaryDirectory(prefix="pbpstats-baseline-") as folder:
        working = Path(folder) / "baseline"
        shutil.copytree(reference, working)
        if args.candidate:
            shutil.copytree(
                args.candidate.resolve() / "pbpstats",
                working / "pbpstats",
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__"),
            )
        code = (
            "import sys,socket; sys.path.insert(0,sys.argv[1]); "
            "socket.socket.connect=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('Unexpected network access')); "
            "import pytest; raise SystemExit(pytest.main(['-q','-p','no:cacheprovider','tests','--junitxml='+sys.argv[2]]))"
        )
        run = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                code,
                str(working),
                str(output / "junit.xml"),
            ],
            cwd=str(working),
            text=True,
            capture_output=True,
            encoding="utf-8",
            timeout=120,
        )
    (output / "pytest.txt").write_text(run.stdout + run.stderr, encoding="utf-8")
    tree = ET.parse(output / "junit.xml")
    cases = tree.findall(".//testcase")
    failures = {
        case.attrib["classname"] + "." + case.attrib["name"]: case.find("failure")
        for case in cases
        if case.find("failure") is not None
    }
    errors = tree.findall(".//error")
    skipped = tree.findall(".//skipped")
    correct_causes = all(
        "'StatsFreeThrow' object has no attribute 'game_id'"
        in failure.attrib.get("message", "")
        for failure in failures.values()
    )
    result = dict(
        total=len(cases),
        passed=len(cases) - len(failures) - len(errors) - len(skipped),
        failures=list(failures),
        errors=len(errors),
        skipped=len(skipped),
        expected_failures_confirmed=set(failures) == expected and correct_causes,
    )
    (output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    if (
        run.returncode != 1
        or errors
        or skipped
        or not result["expected_failures_confirmed"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
