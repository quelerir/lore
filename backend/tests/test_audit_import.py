def test_audit_package_imports_without_airflow():
    import audit.http_api.routes
    import audit.http_api.factory
    import audit.read_service
    import audit.read_repositories
    import audit.read_adapters
    import audit.read_cursor
    from audit._vendor.run_status import RunStatus

    assert RunStatus.SUCCESS == "success"
    assert hasattr(audit.http_api.routes, "create_audit_router")
    assert hasattr(audit.read_service, "AuditReadService")
