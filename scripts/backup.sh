#!/usr/bin/env bash
# Dump the entire analysed dataset (transcripts + analysis) to a single SQL file.
# Restore instantly with scripts/restore.sh — so a reboot or an accidental
# `docker compose down -v` can never cost you the pipeline run before a demo.
#
#   ./scripts/backup.sh            # writes data/backup/callradar_YYYYmmdd_HHMM.sql.gz
#
set -euo pipefail
cd "$(dirname "$0")/.."

OUT_DIR="data/backup"
mkdir -p "$OUT_DIR"
STAMP="$(date +%Y%m%d_%H%M)"
OUT="$OUT_DIR/callradar_${STAMP}.sql.gz"

echo "Dumping database -> $OUT"
docker compose exec -T db pg_dump -U callradar -d callradar --clean --if-exists \
  | gzip > "$OUT"

# Keep a stable 'latest' pointer for restore.sh.
cp "$OUT" "$OUT_DIR/callradar_latest.sql.gz"

ROWS="$(docker compose exec -T db psql -U callradar -d callradar -t -c 'SELECT count(*) FROM calls;' | tr -d ' \r')"
echo "Backed up $ROWS calls."
echo "Size: $(du -h "$OUT" | cut -f1)"
echo "Restore later with: ./scripts/restore.sh"
