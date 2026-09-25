#!/bin/bash
# One-shot production installer for Amiri Insurance.
# Create .env yourself from .env.example, then:
#   sudo bash deploy/setup.sh
# Optional: DOMAIN=... CERTBOT_EMAIL=... SKIP_CERTBOT=1

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash deploy/setup.sh"
  exit 1
fi

SRC="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
APP_DIR="${APP_DIR:-/var/www/amiri}"
SKIP_CERTBOT="${SKIP_CERTBOT:-0}"
APP_USER="${APP_USER:-www-data}"

if [ ! -f "$SRC/wsgi.py" ] || [ ! -f "$SRC/requirements.txt" ]; then
  echo "This script must live in the project (deploy/setup.sh next to wsgi.py)."
  exit 1
fi

log() { echo "[amiri] $*"; }

install_env() {
  if [ -f "$APP_DIR/.env" ]; then
    log "Using existing ${APP_DIR}/.env"
  elif [ -f "$SRC/.env" ]; then
    cp "$SRC/.env" "$APP_DIR/.env"
    log "Copied .env from the project folder"
  else
    echo "Create ${APP_DIR}/.env yourself first."
    echo "  cp ${SRC}/.env.example ${APP_DIR}/.env"
    echo "  nano ${APP_DIR}/.env"
    echo "Fill SECRET_KEY, ADMIN_PASSWORD, DATABASE_URL, POSTGRES_PASSWORD, and CRON_TOKEN."
    exit 1
  fi
  chmod 640 "$APP_DIR/.env"
}

validate_env() {
  python3 - "$APP_DIR/.env" <<'PY'
import sys
from pathlib import Path
from urllib.parse import urlparse, unquote

vals = {}
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    vals[key] = value.strip().strip("'").strip('"')

missing = []
secret = vals.get("SECRET_KEY", "")
if secret in {"", "replace-with-a-long-random-string", "secret", "changeme"} or len(secret) < 24:
    missing.append("SECRET_KEY (24+ random characters)")
admin = vals.get("ADMIN_PASSWORD", "")
if admin.lower() in {"", "replace-with-a-strong-password", "admin", "password", "admin@amiri123"} or len(admin) < 12:
    missing.append("ADMIN_PASSWORD (12+ characters, first admin only)")
db = vals.get("DATABASE_URL", "")
if not db or "replace-with-a-long-random-string" in db:
    missing.append("DATABASE_URL")
cron = vals.get("CRON_TOKEN", "")
if cron in {"", "replace-with-a-random-token"} or len(cron) < 16:
    missing.append("CRON_TOKEN (16+ random characters)")
pg = vals.get("POSTGRES_PASSWORD", "")
if not pg or pg in {"replace-with-a-long-random-string", "amiri"}:
    parsed = urlparse(db)
    pg = unquote(parsed.password or "")
if not pg or pg in {"replace-with-a-long-random-string", "amiri"} or len(pg) < 12:
    missing.append("POSTGRES_PASSWORD or a password inside DATABASE_URL")
if missing:
    print("Fill these in .env, then rerun:")
    for item in missing:
        print(" -", item)
    sys.exit(1)
PY
}

db_host() {
  python3 - "$APP_DIR/.env" <<'PY'
from pathlib import Path
from urllib.parse import urlparse
import sys
db = ""
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if line.startswith("DATABASE_URL="):
        db = line.split("=", 1)[1].strip().strip("'").strip('"')
print(urlparse(db).hostname or "")
PY
}

pg_password() {
  python3 - "$APP_DIR/.env" <<'PY'
from pathlib import Path
from urllib.parse import urlparse, unquote
import sys
vals = {}
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    vals[key] = value.strip().strip("'").strip('"')
url_pw = unquote(urlparse(vals.get("DATABASE_URL") or "").password or "")
pg = url_pw or vals.get("POSTGRES_PASSWORD") or ""
print(pg)
PY
}

public_domain() {
  python3 - "$APP_DIR/.env" <<'PY'
from pathlib import Path
from urllib.parse import urlparse
import sys
url = ""
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if line.startswith("PUBLIC_URL="):
        url = line.split("=", 1)[1].strip().strip("'").strip('"')
host = urlparse(url).hostname or ""
if host.startswith("www."):
    host = host[4:]
print(host)
PY
}

env_get() {
  python3 - "$APP_DIR/.env" "$1" <<'PY'
from pathlib import Path
import sys
key = sys.argv[2]
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if line.startswith(key + "="):
        print(line.split("=", 1)[1])
        break
PY
}

write_nginx() {
  local have_certs=0
  if [ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
    have_certs=1
  fi
  local dest="/etc/nginx/sites-available/amiri"
  if [ "$have_certs" -eq 1 ]; then
    cat > "$dest" <<EOF
upstream amiri_app {
    server ${APP_BIND};
    keepalive 16;
}

server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN} ${WWW_DOMAIN};
    client_max_body_size 16m;
    server_tokens off;
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://${DOMAIN}\$request_uri; }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${DOMAIN} ${WWW_DOMAIN};
    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
    client_max_body_size 16m;
    server_tokens off;
    proxy_hide_header Server;
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options SAMEORIGIN always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
    gzip on;
    gzip_types text/plain text/css application/json application/javascript image/svg+xml;
    root ${APP_DIR};
    location ^~ /static/uploads/crm { deny all; return 404; }
    location ^~ /uploads/crm { deny all; return 404; }
    location /static/ {
        alias ${APP_DIR}/static/;
        expires 7d;
        access_log off;
    }
    location /healthz {
        allow 127.0.0.1;
        allow ::1;
        deny all;
        proxy_pass http://amiri_app;
        proxy_set_header Host \$host;
        access_log off;
    }
    location / {
        proxy_pass http://amiri_app;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Connection "";
        proxy_read_timeout 60s;
    }
}
EOF
  else
    cat > "$dest" <<EOF
upstream amiri_app {
    server ${APP_BIND};
    keepalive 16;
}

server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN} ${WWW_DOMAIN};
    client_max_body_size 16m;
    server_tokens off;
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location ^~ /static/uploads/crm { deny all; return 404; }
    location ^~ /uploads/crm { deny all; return 404; }
    location /static/ {
        alias ${APP_DIR}/static/;
        expires 7d;
        access_log off;
    }
    location /healthz {
        allow 127.0.0.1;
        allow ::1;
        deny all;
        proxy_pass http://amiri_app;
        proxy_set_header Host \$host;
        access_log off;
    }
    location / {
        proxy_pass http://amiri_app;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Connection "";
        proxy_read_timeout 60s;
    }
}
EOF
  fi
  ln -sfn "$dest" /etc/nginx/sites-enabled/amiri
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  systemctl reload nginx
}

log "Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip nginx postgresql postgresql-client \
  rsync curl ufw certbot python3-certbot-nginx

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

log "Syncing app to ${APP_DIR}"
mkdir -p "$APP_DIR" /var/www/html /var/backups/amiri
rsync -a \
  --exclude '.env' \
  --exclude '.env.local' \
  --exclude 'venv/' \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '.git/' \
  --exclude 'data/uploads/' \
  --exclude 'static/uploads/blog/' \
  "$SRC/" "$APP_DIR/"
mkdir -p "$APP_DIR/data/uploads/crm" "$APP_DIR/static/uploads/blog"
if [ -d "$SRC/data/uploads/crm" ]; then
  rsync -a "$SRC/data/uploads/crm/" "$APP_DIR/data/uploads/crm/"
fi
if [ -d "$SRC/static/uploads/blog" ]; then
  rsync -a "$SRC/static/uploads/blog/" "$APP_DIR/static/uploads/blog/"
fi
chmod +x "$APP_DIR/deploy/backup.sh" "$APP_DIR/deploy/setup.sh"

install_env
validate_env
DOMAIN="${DOMAIN:-$(public_domain)}"
DOMAIN="${DOMAIN:-amiriinsuranceagency.com}"
WWW_DOMAIN="www.${DOMAIN}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-$(env_get BREVO_NOTIFY_EMAIL)}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-info@${DOMAIN}}"
PG_PASS="$(pg_password)"
DB_HOST="$(db_host)"
APP_BIND="$(env_get GUNICORN_BIND)"
APP_BIND="${APP_BIND:-127.0.0.1:8000}"
APP_PORT="${APP_BIND##*:}"
chmod 640 "$APP_DIR/.env"

log "Creating Python environment"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [ "$DB_HOST" = "127.0.0.1" ] || [ "$DB_HOST" = "localhost" ]; then
  log "Creating local Postgres role and database"
  systemctl enable --now postgresql
  if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='amiri'" | grep -q 1; then
    sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE USER amiri WITH PASSWORD '${PG_PASS}';"
  else
    sudo -u postgres psql -v ON_ERROR_STOP=1 -c "ALTER USER amiri WITH PASSWORD '${PG_PASS}';"
  fi
  if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='amiri'" | grep -q 1; then
    sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE DATABASE amiri OWNER amiri;"
  fi
else
  log "Using remote DATABASE_URL host ${DB_HOST}; not creating a local role"
fi

log "Setting ownership"
chown -R "$APP_USER:$APP_USER" "$APP_DIR" /var/backups/amiri
chown root:root "$APP_DIR/deploy/setup.sh" "$APP_DIR/deploy/backup.sh"
chmod 750 "$APP_DIR/data" "$APP_DIR/data/uploads" "$APP_DIR/data/uploads/crm"
chmod 640 "$APP_DIR/.env"
chown "$APP_USER:$APP_USER" "$APP_DIR/.env"

log "Seeding database"
sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && APP_ENV=production '$APP_DIR/venv/bin/python' -c 'from app import boot; boot()'"

log "Installing systemd service"
systemctl stop amiri 2>/dev/null || true
fuser -k "${APP_PORT}/tcp" 2>/dev/null || true
cp "$APP_DIR/deploy/amiri.service" /etc/systemd/system/amiri.service
sed -i "s#/var/www/amiri#${APP_DIR}#g" /etc/systemd/system/amiri.service
sed -i "s#GUNICORN_BIND=.*#GUNICORN_BIND=${APP_BIND}#" /etc/systemd/system/amiri.service
systemctl daemon-reload
systemctl enable --now amiri
systemctl restart amiri
sleep 2
health_hdr=()
if [ -n "$(env_get HEALTH_TOKEN)" ]; then
  health_hdr=(-H "X-Health-Token: $(env_get HEALTH_TOKEN)")
fi
if ! curl -fsS "${health_hdr[@]}" "http://${APP_BIND}/healthz" | grep -q '"ok":true'; then
  echo "App did not become healthy. Check: journalctl -u amiri -e"
  journalctl -u amiri -n 40 --no-pager || true
  exit 1
fi

log "Configuring firewall"
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

log "Configuring nginx"
write_nginx

if [ "$SKIP_CERTBOT" != "1" ]; then
  log "Requesting TLS certificate"
  if certbot --nginx --non-interactive --agree-tos --redirect \
      -m "$CERTBOT_EMAIL" -d "$DOMAIN" -d "$WWW_DOMAIN"; then
    write_nginx
  else
    echo "Certbot did not finish. DNS may not point here yet. HTTP is live; rerun this script later."
  fi
fi

CRON_TOKEN="$(env_get CRON_TOKEN)"
cat > /etc/cron.d/amiri <<EOF
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
0 7 * * * ${APP_USER} curl -fsS -H "X-Cron-Token: ${CRON_TOKEN}" https://${DOMAIN}/api/cron/renewals >/dev/null
15 2 * * * ${APP_USER} ${APP_DIR}/deploy/backup.sh ${APP_DIR}
EOF
chmod 600 /etc/cron.d/amiri

log "Done"
echo
echo "Site: https://${DOMAIN}"
echo "Admin: https://${DOMAIN}/admin/login"
echo "First login: scan the authenticator secret, then enter the 6-digit code."
echo "Health (on the server): curl -sS http://${APP_BIND}/healthz"
echo "Logs: journalctl -u amiri -e"
echo "To update later, copy new files and rerun: sudo bash ${APP_DIR}/deploy/setup.sh"
