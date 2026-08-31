from uuid import uuid4

import pytest
from pydantic import ValidationError

from resolution_agent.runbooks import RunbookVersion, contains_unresolved_placeholders, validate_runbook_parameters


def test_approved_mutating_runbook_requires_validation_and_rollback() -> None:
    with pytest.raises(ValidationError, match="validation and rollback"):
        RunbookVersion(
            runbook_id=uuid4(), version=1, status="approved", owner="sre", service="api",
            alert_family="availability", risk="low", action=["restart"], validation=[], rollback=[],
        )


def test_runbook_parameters_reject_unknown_and_unresolved_values() -> None:
    schema = {"type": "object", "properties": {"service": {"type": "string"}}, "required": ["service"]}
    with pytest.raises(ValueError, match="unknown"):
        validate_runbook_parameters(schema, {"service": "api", "command": "rm -rf /"})
    with pytest.raises(ValueError, match="unresolved placeholder"):
        validate_runbook_parameters(schema, {"service": "${service}"})


def test_placeholder_detector_covers_catalog_and_template_syntax() -> None:
    assert contains_unresolved_placeholders(["kubectl restart ${service}"])
    assert contains_unresolved_placeholders(["restore <original>"])
    assert contains_unresolved_placeholders(["deploy {{ namespace }}"])
