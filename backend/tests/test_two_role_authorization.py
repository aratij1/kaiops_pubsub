from common.authorization import OperationalRole, operational_role, role_is_allowed


def test_canonical_roles_are_authorized() -> None:
    assert role_is_allowed("ADMIN", {OperationalRole.ADMIN})
    assert role_is_allowed("HITL_APPROVER", {OperationalRole.HITL_APPROVER})


def test_legacy_operational_roles_are_mapped_without_rewriting_records() -> None:
    assert operational_role("Administrator") is OperationalRole.ADMIN
    assert operational_role("L3 Engineer") is OperationalRole.HITL_APPROVER
    assert operational_role("L2 Engineer") is OperationalRole.HITL_APPROVER


def test_read_only_legacy_roles_do_not_gain_write_authority() -> None:
    allowed = {OperationalRole.ADMIN, OperationalRole.HITL_APPROVER}
    assert not role_is_allowed("Executive", allowed)
    assert not role_is_allowed("L1 Operator", allowed)
    assert not role_is_allowed("unknown", allowed)
