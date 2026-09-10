"""Golden-file tests that freeze validator behaviour across the refactor.

Each case pairs an input bill (``<case>.json``) with the exact list of flag
strings the validator must produce (``<case>.flags.json``). These were frozen in
segment 1 and must remain byte-identical through every later segment. In segment
2 the underlying engine returns structured ``Finding`` objects; ``check_bill``
projects them back to strings, and these tests prove that projection reproduces
the original flags, in the original order, on the original inputs.

When a real bill is available it should be added here as another case, giving
the suite a real-world anchor alongside the synthetic ones.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from voltscope.validator import check_bill

FIXTURES = Path(__file__).parent / "fixtures"
CASES = sorted(
    p.stem
    for p in FIXTURES.glob("*.json")
    if not p.name.endswith(".flags.json")
)


@pytest.mark.parametrize("case", CASES)
def test_validator_matches_golden(case: str) -> None:
    bill = json.loads((FIXTURES / f"{case}.json").read_text(encoding="utf-8"))
    expected = json.loads((FIXTURES / f"{case}.flags.json").read_text(encoding="utf-8"))
    assert check_bill(bill) == expected
