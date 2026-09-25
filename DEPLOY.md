# Deploy Amiri Insurance

The live site is a Flask app behind **gunicorn** and **nginx**, with **PostgreSQL**. Do not run `python app.py` in production.

## Fast path (one file)

1. Copy the project to the VPS.
2. Create `.env` yourself (`cp .env.example .env` then edit). The installer will not write secrets.
3. Run:

```bash
sudo bash deploy/setup.sh
```

That installs packages, creates local Postgres if `DATABASE_URL` is on this machine, starts gunicorn, opens nginx, requests HTTPS, and schedules renewals plus backups.

Generate values on the server if you want:

```bash
python3 -c "import secrets; print(secrets.token_hex(32)); print(secrets.token_hex(24))"
```

Use the first line as `SECRET_KEY` and the second as `CRON_TOKEN`. Set `ADMIN_PASSWORD` (12+) and the same database password in both `POSTGRES_PASSWORD` and `DATABASE_URL`.

If DNS is not ready: `SKIP_CERTBOT=1`. Rerun the same command later to add TLS. The script is safe to run again and will not overwrite `.env`.

First admin login: scan the authenticator secret, then enter the 6-digit code.

Manual steps below are only if you want to do each part yourself.

## What you need

- Ubuntu VPS (or similar) with Python 3.12, nginx, and PostgreSQL
- A domain pointed at the server (`amiriinsuranceagency.com`)
- Brevo API key if invoice and quote emails should send
- A strong admin password and a long `SECRET_KEY`

## 1. Server packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx postgresql
```

## 2. App files

```bash
sudo mkdir -p /var/www/amiri
sudo chown "$USER:$USER" /var/www/amiri
# copy the project here (git clone or scp), then:
cd /var/www/amiri
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 3. Environment

```bash
cp .env.example .env
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Put the printed value in `SECRET_KEY`. Then set:

- `ADMIN_PASSWORD` — 12+ characters; used only to create the first admin if the users table is empty
- After the first sign-in, enroll an authenticator app (Google Authenticator or Authy)
- `DATABASE_URL` — production Postgres
- `PUBLIC_URL=https://amiriinsuranceagency.com`
- `APP_ENV=production` and `FLASK_DEBUG=0`
- `BREVO_API_KEY` if you want email
- `CRON_TOKEN` for nightly renewal notices

If the database already has users, changing `ADMIN_PASSWORD` in `.env` does **not** change the login. Reset it from the admin users screen instead.

## 4. Database

Create the database, then start the app once so tables seed:

```bash
sudo -u postgres psql -c "CREATE USER amiri WITH PASSWORD 'choose-a-strong-password';"
sudo -u postgres psql -c "CREATE DATABASE amiri OWNER amiri;"
source venv/bin/activate
APP_ENV=production python -c "from app import boot; boot()"
```

To move local data, dump from your machine and restore on the server:

```bash
pg_dump "$DATABASE_URL" > amiri.sql
psql "$DATABASE_URL" < amiri.sql
```

Blog images live in `static/uploads/blog/`. Client documents (IDs, logbooks, PINs) live in `data/uploads/crm/` and are not public. Copy both folders if you need existing files.

## 5. Gunicorn + systemd

```bash
sudo cp deploy/amiri.service /etc/systemd/system/amiri.service
sudo systemctl daemon-reload
sudo systemctl enable --now amiri
curl -sS http://127.0.0.1:8000/healthz
```

You should see `{"ok":true,"db":true}`.

## 6. Nginx + HTTPS

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/amiri
sudo ln -sf /etc/nginx/sites-available/amiri /etc/nginx/sites-enabled/amiri
sudo nginx -t && sudo systemctl reload nginx
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d amiriinsuranceagency.com -d www.amiriinsuranceagency.com
```

Uncomment the `ssl_certificate` lines in `deploy/nginx.conf` if certbot does not edit the site file for you.

## 7. Renewal cron

Once a day, hit the protected renewal URL:

```bash
# /etc/cron.d/amiri-renewals
0 7 * * * www-data curl -fsS -H "X-Cron-Token: YOUR_CRON_TOKEN" https://amiriinsuranceagency.com/api/cron/renewals >/dev/null
15 2 * * * www-data /var/www/amiri/deploy/backup.sh /var/www/amiri
```

## After each update

```bash
cd /var/www/amiri
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart amiri
```

## Docker (optional)

Postgres only, for local work (port **5433**):

```bash
docker compose up -d db
```

App + database:

```bash
docker compose --profile app up --build
```

That profile expects a real `SECRET_KEY` and `ADMIN_PASSWORD` in `.env`.

## Go-live checklist

- [ ] `SECRET_KEY` is random and at least 24 characters
- [ ] `ADMIN_PASSWORD` is not the example default
- [ ] `DATABASE_URL` points at production Postgres
- [ ] `/healthz` returns `ok: true`
- [ ] Homepage, quote form, and `/admin/login` work over HTTPS
- [ ] Invoice email works after `BREVO_API_KEY` is set
- [ ] `CRON_TOKEN` is set if you use renewal notices
- [ ] First admin sign-in enrolls an authenticator app
- [ ] Nightly `deploy/backup.sh` is scheduled
- [ ] `.env` is not in git
- [ ] Client files are in `data/uploads/crm/`, not under `static/`
