#!/usr/bin/env bash
# Restore the analysed dataset from a backup made by scripts/backup.sh.
#
#   ./scripts/restore.sh                                  # restores data/backup/callradar_latest.sql.gz
#   ./scripts/restore.sh data/backup/callradar_XXXX.sql.gz  # restore a specific dump
#
# The db service must be up (docker compose up -d db). This drops and recreates
# the calls table from the dump, so no re-transcription is needed.
set -euo pipefail
cd "$(dirname "$0")/.."

SRC="${1:-data/backup/callradar_latest.sql.gz}"
if [ ! -f "$SRC" ]; then
  echo "Backup not found: $SRC"
  echo "Run ./scripts/backup.sh first, or pass a path to a .sql.gz dump."
  exit 1
fi

echo "Waiting for the database to be ready..."
until docker compose exec -T db pg_isready -U callradar >/dev/null 2>&1; do sleep 1; done

echo "Restoring $SRC ..."
gunzip -c "$SRC" | docker compose exec -T db psql -U callradar -d callradar >/dev/null

ROWS="$(docker compose exec -T db psql -U callradar -d callradar -t -c 'SELECT count(*) FROM calls;' | tr -d ' \r')"
echo "Restored $ROWS calls. The dashboard and API are ready — no re-transcription needed."
