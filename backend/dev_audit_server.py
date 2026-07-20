"""DEV-ONLY standalone launcher for the audit read API.

Mounts /api/v1/audit on a bare FastAPI app (no Chainlit chat/data-layer/authentik)
so the FileViewer can be demoed against the real lore_core DB. Run with
AUDIT_DEV_ALLOW_ANON=1 to skip auth locally. Never use in production.

    AUDIT_DEV_ALLOW_ANON=1 uv run python dev_audit_server.py
"""

from fastapi import FastAPI

from audit.mount import attach_audit_router

app = FastAPI(title="Audit dev server")
attached = attach_audit_router(app)


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"ok": True, "audit_mounted": attached}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
