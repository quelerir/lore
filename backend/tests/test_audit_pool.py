from audit.pool import AuditConnectionPool


class _FakeCtx:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *a):
        return False


class _FakePool:
    def __init__(self):
        self.closed = False

    def connection(self):
        return _FakeCtx("CONN")

    def close(self):
        self.closed = True


def test_acquire_yields_connection_from_pool():
    pool = AuditConnectionPool(_FakePool())
    with pool.acquire() as conn:
        assert conn == "CONN"


def test_close_delegates_to_pool():
    fake = _FakePool()
    AuditConnectionPool(fake).close()
    assert fake.closed is True
