"""Deterministic smoke test runner for Soraya's router.

Loads examples/smoke_tests.json, runs each prompt through router.route_user_turn,
and compares the resulting selected_route and soraya_mode against the
expected_route and expected_mode fields. Prints a concise pass/fail report
and exits with a non-zero status if any case fails.

Run from the repo root:

    python scripts/run_smoke_tests.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SMOKE_TESTS_PATH = REPO_ROOT / "examples" / "smoke_tests.json"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from router import route_user_turn  # noqa: E402


def load_cases(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data.get("prompts", [])


def run() -> int:
    cases = load_cases(SMOKE_TESTS_PATH)
    if not cases:
        print("No smoke test cases found.")
        return 1

    failures = 0
    print(f"Running {len(cases)} deterministic router smoke tests...\n")
    for case in cases:
        case_id = case.get("id", "?")
        prompt = case.get("prompt", "")
        expected_route = case.get("expected_route")
        expected_mode = case.get("expected_mode")

        decision = route_user_turn(prompt)
        actual_route = decision.selected_route.value
        actual_mode = decision.soraya_mode.value

        route_ok = actual_route == expected_route
        mode_ok = actual_mode == expected_mode
        passed = route_ok and mode_ok

        status = "PASS" if passed else "FAIL"
        print(f"[{status}] case {case_id}: {prompt!r}")
        print(f"    route: expected={expected_route!r} actual={actual_route!r}")
        print(f"    mode:  expected={expected_mode!r} actual={actual_mode!r}")

        if not passed:
            failures += 1

    total = len(cases)
    passed = total - failures
    print(f"\nSummary: {passed}/{total} passed, {failures} failed.")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
