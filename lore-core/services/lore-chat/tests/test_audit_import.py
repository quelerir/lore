def test_audit_package_imports_without_airflow():
    import audit.http_api.routes
    import audit.http_api.factory
    import lore_audit.read_service
    import lore_audit.read_repositories
    import lore_audit.read_adapters
    import lore_audit.read_cursor
    from lore_audit.run_status import RunStatus

    assert RunStatus.SUCCESS == "success"
    assert hasattr(audit.http_api.routes, "create_audit_router")
    assert hasattr(lore_audit.read_service, "AuditReadService")
