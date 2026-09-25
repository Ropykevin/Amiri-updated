#!/bin/sh
# Encrypted-at-rest files stay as-is. Dump Postgres and copy private uploads.
set -eu
ROOT="${1:-/var/www/amiri}"
DEST="${BACKUP_DIR:-/var/backups/amiri}"
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$DEST"
. "$ROOT/.env"
pg_dump "$DATABASE_URL" > "$DEST/amiri-$STAMP.sql"
tar -C "$ROOT" -czf "$DEST/amiri-files-$STAMP.tgz" data/uploads/crm static/uploads/blog
find "$DEST" -type f -mtime +14 -delete
echo "Wrote $DEST/amiri-$STAMP.sql"
