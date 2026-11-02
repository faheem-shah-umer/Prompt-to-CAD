"""Retain automated test output. This runner never starts paid live agent/service tests."""

import argparse
import json
import time
import unittest
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output or root / "artifacts/validation"
    output.mkdir(parents=True, exist_ok=True)
    pattern = "test_*.py"
    suite = unittest.defaultTestLoader.discover(
        str(root / "backend/tests"), pattern=pattern
    )
    started = time.monotonic()
    with (output / "automated-tests.log").open("w", encoding="utf-8") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    report = {
        "passed": result.wasSuccessful(),
        "tests": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "elapsed_seconds": time.monotonic() - started,
        "pattern": pattern,
        "live_provider_inference": False,
        "text_only_release": True,
    }
    (output / "automated-tests.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report), flush=True)
    for test, traceback in result.failures + result.errors:
        print(f"{test}\n{traceback}", flush=True)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
