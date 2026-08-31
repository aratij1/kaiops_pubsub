import importlib.util
import sys
from pathlib import Path


def load_stress_module():
    module_path = Path("scripts/stress_ingest_gateway_alerts.py")
    spec = importlib.util.spec_from_file_location("stress_ingest_gateway_alerts", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # The module's Stats dataclass uses `from __future__ import annotations`
    # (string annotations), which dataclasses resolves via
    # sys.modules[cls.__module__] — register the module before exec_module
    # runs the class body, or that lookup returns None.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_percentile_of_empty_list_is_zero() -> None:
    module = load_stress_module()
    assert module.percentile([], 95) == 0.0


def test_percentile_matches_known_values() -> None:
    module = load_stress_module()
    values = sorted(float(v) for v in range(1, 101))  # 1..100, 0-indexed nearest-rank

    assert module.percentile(values, 50) == 51.0
    assert module.percentile(values, 99) == 99.0
    assert module.percentile(values, 100) == 100.0


def test_percentile_single_value() -> None:
    module = load_stress_module()
    assert module.percentile([42.0], 95) == 42.0
