def test_audit_package_imports_without_airflow():
    import lore_audit_api.http.routes
    import lore_audit_api.factory
    import lore_audit.read_service
    import lore_audit.repository
    import lore_audit.read_adapters
    import lore_audit.read_cursor
    from lore_core_domain.run_status import RunStatus

    import audit_mount
    import audit_auth

    assert RunStatus.SUCCESS == "success"
    assert hasattr(lore_audit_api.http.routes, "create_audit_router")
    assert hasattr(lore_audit_api.factory, "create_audit_app")
    assert hasattr(lore_audit_api.factory, "build_audit_service")
    assert hasattr(lore_audit.read_service, "AuditReadService")
    assert hasattr(audit_mount, "attach_audit_router")
    assert hasattr(audit_auth, "chat_auth_dependency")
