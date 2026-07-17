"""Регресс: соединение НЕ шлёт startup-параметры (их рвёт transaction-pooling
пулер), read-only и statement_timeout навешиваются ПО-ТРАНЗАКЦИОННО, а само
соединение гарантированно закрывается. Живая БД не нужна."""

import asyncio


LEGAL = "toast_tbl_ec48a6d52d16ab405f95"


def _run(coro):
    return asyncio.run(coro)


class _FakeTxn:
    def __init__(self, conn, readonly):
        conn.readonly_flags.append(readonly)

    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self):
        self.readonly_flags: list[bool] = []
        self.executed: list[str] = []
        self.closed = False

    def transaction(self, readonly=False):
        return _FakeTxn(self, readonly)

    async def execute(self, query, *args):
        self.executed.append(query)

    async def fetch(self, query, *args):
        return []

    async def close(self):
        self.closed = True


def _patch(monkeypatch):
    import toast.executor as ex

    conn = _FakeConn()
    captured: dict = {}

    async def fake_connect(dsn, **kwargs):
        captured["dsn"] = dsn
        captured.update(kwargs)
        return conn

    monkeypatch.setattr(ex.asyncpg, "connect", fake_connect)
    return ex, conn, captured


def test_connect_has_no_startup_params(monkeypatch):
    ex, conn, captured = _patch(monkeypatch)

    async def run():
        e = ex.PgExecutor("postgresql://u:p@pooler:6543/db")
        await e.fetch_columns(LEGAL)

    _run(run())
    # Ровно причина падения за пулером: startup-параметры соединения.
    assert "server_settings" not in captured
    # read-only и timeout — внутри транзакции; соединение закрыто.
    assert conn.readonly_flags == [True]
    assert any("statement_timeout" in q for q in conn.executed)
    assert conn.closed


def test_run_select_uses_readonly_transaction(monkeypatch):
    ex, conn, _ = _patch(monkeypatch)

    async def run():
        e = ex.PgExecutor("postgresql://u:p@pooler:6543/db")
        await e.run_select(
            f"SELECT column_1 FROM splitter_toast.{LEGAL}", LEGAL
        )

    _run(run())
    assert conn.readonly_flags == [True]
    assert any("statement_timeout" in q for q in conn.executed)
    assert conn.closed
