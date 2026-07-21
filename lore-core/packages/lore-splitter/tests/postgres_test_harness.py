from __future__ import annotations

import contextlib
import subprocess
import time
import uuid
from collections.abc import Iterator

import psycopg

POSTGRES_IMAGE = "postgres:16-alpine"
POSTGRES_PASSWORD = "lore_test_only"
POSTGRES_DATABASE = "lore_test"
TABLESPACE_DIRECTORY = "/var/lib/postgresql/lore_tablespaces/lore_toast"


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _published_port(container_name: str) -> int:
    output = _docker("port", container_name, "5432/tcp").stdout.strip()
    if not output:
        raise RuntimeError("postgres_container_has_no_published_port")
    return int(output.rsplit(":", 1)[1])


def _wait_for_postgres(container_name: str, *, timeout_seconds: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_output = ""
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "docker",
                "exec",
                container_name,
                "pg_isready",
                "-h",
                "127.0.0.1",
                "-U",
                "postgres",
                "-d",
                POSTGRES_DATABASE,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        last_output = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            return
        time.sleep(0.25)
    raise RuntimeError(f"postgres_container_not_ready: {last_output}")


@contextlib.contextmanager
def ephemeral_postgres() -> Iterator[psycopg.Connection]:
    """Yield a disposable local PostgreSQL connection and always remove its container."""
    container_name = f"lore-audit-test-{uuid.uuid4().hex}"
    connection: psycopg.Connection | None = None
    try:
        _docker(
            "run",
            "--detach",
            "--rm",
            "--name",
            container_name,
            "--env",
            f"POSTGRES_PASSWORD={POSTGRES_PASSWORD}",
            "--env",
            f"POSTGRES_DB={POSTGRES_DATABASE}",
            "--publish",
            "127.0.0.1::5432",
            POSTGRES_IMAGE,
        )
        _docker(
            "exec",
            "--user",
            "root",
            container_name,
            "mkdir",
            "-p",
            TABLESPACE_DIRECTORY,
        )
        _docker(
            "exec",
            "--user",
            "root",
            container_name,
            "chown",
            "postgres:postgres",
            TABLESPACE_DIRECTORY,
        )
        _wait_for_postgres(container_name)
        connection = psycopg.connect(
            host="127.0.0.1",
            port=_published_port(container_name),
            dbname=POSTGRES_DATABASE,
            user="postgres",
            password=POSTGRES_PASSWORD,
            connect_timeout=10,
        )
        yield connection
    finally:
        if connection is not None:
            connection.close()
        subprocess.run(
            ["docker", "rm", "--force", container_name],
            check=False,
            capture_output=True,
            text=True,
        )
