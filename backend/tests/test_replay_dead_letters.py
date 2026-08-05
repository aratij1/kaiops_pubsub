import base64
import importlib.util
import json
from pathlib import Path


def load_replay_module():
    module_path = Path("scripts/replay_dead_letters.py")
    spec = importlib.util.spec_from_file_location("replay_dead_letters", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_decode_body_parses_plain_json_string_payload() -> None:
    module = load_replay_module()
    envelope = {
        "failed_topic": "raw-alerts",
        "payload": {"id": "alert-1"},
        "error": "TimeoutError",
        "attempts": 2,
    }
    message = {"payload": json.dumps(envelope), "payload_encoding": "string"}

    decoded = module.decode_body(message)

    assert decoded == envelope


def test_decode_body_parses_base64_encoded_payload() -> None:
    module = load_replay_module()
    envelope = {"failed_topic": "raw-alerts", "payload": {"id": "alert-2"}}
    message = {
        "payload": base64.b64encode(json.dumps(envelope).encode("utf-8")).decode("ascii"),
        "payload_encoding": "base64",
    }

    decoded = module.decode_body(message)

    assert decoded == envelope


def test_decode_body_returns_none_for_malformed_json() -> None:
    module = load_replay_module()
    message = {"payload": "not-json", "payload_encoding": "string"}

    assert module.decode_body(message) is None


def test_decode_body_returns_none_for_non_dict_json() -> None:
    module = load_replay_module()
    message = {"payload": json.dumps([1, 2, 3]), "payload_encoding": "string"}

    assert module.decode_body(message) is None
