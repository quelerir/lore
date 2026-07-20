from audit.assembly import build_audit_router, build_audit_service


class _S:
    audit_db_dsn = None
    jwt_secret = "test-secret"


def test_service_is_none_without_db_or_key():
    assert build_audit_service(_S()) is None


def test_router_is_none_without_db_or_key():
    assert build_audit_router(_S()) is None
