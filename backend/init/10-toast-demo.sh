#!/bin/bash
# Создаёт демо-БД lore_data (TOAST-слепок) и наполняет её.
# Идемпотентен: можно запускать и при initdb, и вручную на живой БД.
set -euo pipefail

PGUSER="${POSTGRES_USER:-chainlit}"

psql -v ON_ERROR_STOP=1 -U "$PGUSER" -d postgres \
  -tc "SELECT 1 FROM pg_database WHERE datname = 'lore_data'" | grep -q 1 \
  || psql -v ON_ERROR_STOP=1 -U "$PGUSER" -d postgres -c "CREATE DATABASE lore_data"

psql -v ON_ERROR_STOP=1 -U "$PGUSER" -d lore_data \
  -f /docker-entrypoint-initdb.d/toast-demo.sql
echo "toast demo data ready"
