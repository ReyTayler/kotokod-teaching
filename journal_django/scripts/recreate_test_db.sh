#!/usr/bin/env bash
# recreate_test_db.sh — (re)create the isolated test database `journal_test`
# as a schema-only clone of the production `journal` DB (architecture_v2 phase 3).
#
# WHY: project models are managed=False and conftest sets django_db_setup=pass,
# so pytest runs against the DB named in settings. Tests MUST use journal_test,
# never the real `journal` (a full pytest run flushes the target DB).
# config/settings/test.py points pytest here and refuses any non *_test DB.
#
# Reads connection (host/port/user/password) from DATABASE_URL in repo-root .env,
# only swapping the database name. Reads `journal` read-only (pg_dump --schema-only).
#
# Usage (from anywhere):  bash journal_django/scripts/recreate_test_db.sh
set -euo pipefail

PSQL="${PSQL:-/c/Program Files/PostgreSQL/15/bin/psql}"
PGDUMP="${PGDUMP:-/c/Program Files/PostgreSQL/15/bin/pg_dump}"
TEST_DB="${TEST_DB_NAME:-journal_test}"

# repo root = two levels up from this script (journal_django/scripts/..)
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DBURL="$(grep -E '^DATABASE_URL=' "$ROOT/.env" | cut -d'=' -f2- | tr -d '\r\n')"
[ -n "$DBURL" ] || { echo "DATABASE_URL not found in $ROOT/.env" >&2; exit 1; }

ADMIN_URL="$(echo "$DBURL"  | sed -E 's#/[^/]+$#/postgres#')"
TEST_URL="$(echo  "$DBURL"  | sed -E "s#/[^/]+\$#/$TEST_DB#")"

echo "Recreating $TEST_DB (schema clone of production DB)..."
printf 'DROP DATABASE IF EXISTS %s;\nCREATE DATABASE %s OWNER journal;\n' "$TEST_DB" "$TEST_DB" \
  | "$PSQL" -v ON_ERROR_STOP=1 -d "$ADMIN_URL"

echo "Cloning schema (read-only pg_dump --schema-only)..."
"$PGDUMP" --schema-only --no-owner --no-privileges -d "$DBURL" | "$PSQL" -d "$TEST_URL" >/dev/null

TABLES="$(printf "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';\n" \
  | "$PSQL" -tA -d "$TEST_URL")"
echo "Done. $TEST_DB has $TABLES public tables. Run: pytest (uses config.settings.test)"
