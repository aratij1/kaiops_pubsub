from collections import Counter

from scripts.check_ruff_regression import regressions


def test_regressions_reject_new_or_increased_file_rule_debt() -> None:
    baseline = Counter({("backend/app.py", "E501"): 2, ("backend/app.py", "F401"): 1})
    current = Counter({("backend/app.py", "E501"): 3, ("backend/app.py", "F401"): 1, ("scripts/new.py", "B006"): 1})

    assert regressions(baseline, current) == [
        ("backend/app.py", "E501", 2, 3),
        ("scripts/new.py", "B006", 0, 1),
    ]


def test_regressions_allow_debt_reduction_without_weakening_rules() -> None:
    baseline = Counter({("backend/app.py", "E501"): 2, ("backend/app.py", "F401"): 1})
    current = Counter({("backend/app.py", "E501"): 1})

    assert regressions(baseline, current) == []
