# SwiftCart Deployment Guide

This project can be deployed in a production-friendly way for roughly 200 concurrent users if you move off the built-in Flask dev server and off SQLite.

Recommended stack:

- Ubuntu 24.04 VPS
- 2 vCPU minimum, 4 GB RAM minimum
- PostgreSQL
- Gunicorn
- Nginx

## 1. Prepare the server

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx postgresql postgresql-contrib
```

## 2. Create the project folder

```bash
sudo mkdir -p /var/www/swiftcart
sudo chown -R $USER:$USER /var/www/swiftcart
cd /var/www/swiftcart
```

Copy this project into `/var/www/swiftcart`.

## 3. Create the Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 4. Create the PostgreSQL database

```bash
sudo -u postgres psql
```

Inside PostgreSQL:

```sql
CREATE DATABASE swiftcart;
CREATE USER swiftcart WITH PASSWORD 'change_this_password';
GRANT ALL PRIVILEGES ON DATABASE swiftcart TO swiftcart;
\q
```

## 5. Create the environment file

```bash
cp .env.example .env
```

Edit `.env` and set:

- `SECRET_KEY`
- `DATABASE_URL`
- optional Gunicorn worker settings
- `ALLOWED_ORIGINS`
- `OWNER_PASSWORD` before first production boot
- OTP provider settings if you want real email or SMS verification

Example:

```env
FLASK_ENV=production
FLASK_DEBUG=0
SECRET_KEY=put-a-long-random-secret-here
DATABASE_URL=postgresql+psycopg://swiftcart:change_this_password@127.0.0.1:5432/swiftcart
GUNICORN_BIND=127.0.0.1:8000
GUNICORN_WORKERS=4
GUNICORN_THREADS=2
```

Security-focused production settings:

```env
ALLOWED_ORIGINS=https://your-domain.com
PUBLIC_SITE_URL=https://your-domain.com
OWNER_EMAIL=owner@your-domain.com
OWNER_PASSWORD=set-a-unique-long-password
ENABLE_DEMO_LOGINS=0
ENABLE_DEMO_MERCHANT=0
ROTATE_SEEDED_PASSWORDS=0
AUTH_TOKEN_MAX_AGE_SECONDS=604800
PUBLIC_SUPPORT_EMAIL=support@your-domain.com
PUBLIC_BUSINESS_ADDRESS=Your registered business address
```

Notes:

- Do not keep hardcoded owner or demo passwords in code or Railway variables screenshots.
- Set `ENABLE_DEMO_LOGINS=0` on Railway so demo-style seeded accounts are not available on public deployments.
- Keep `ENABLE_DEMO_MERCHANT=0` unless you intentionally want a demo seller account.
- Production now refuses to silently fall back to SQLite unless you explicitly set `ALLOW_SQLITE_IN_PRODUCTION=1`. This prevents user and order data from disappearing on ephemeral hosts.
- `SWIFTCART_EXPOSE_OTP_PREVIEW=1` forces OTP preview responses for testing. Localhost and private-network hosting now show OTP previews automatically even if you run with production-like settings.
- Publish a real support email, business address, and custom domain before asking users to trust the login flow.
- Set `PUBLIC_SITE_URL` to your real custom domain so public traffic can redirect away from the random Railway hostname.
- SwiftCart now uses signed auth tokens for protected API routes, so users must log in again after deployment if they had an old local session stored in the browser.

If you have older user/order data in a SQLite file and are moving to PostgreSQL, restore it after configuring the real database:

```bash
python -m backend.restore_from_sqlite --source backend/database.db
```

## 6. Initialize the app once

```bash
source .venv/bin/activate
export $(grep -v '^#' .env | xargs)
python3 -m backend.app
```

Open a second terminal and check:

```bash
curl http://127.0.0.1:5000/api/health
```

Then stop the dev server with `Ctrl + C`.

## 7. Start Gunicorn

```bash
source .venv/bin/activate
export $(grep -v '^#' .env | xargs)
gunicorn -c gunicorn.conf.py wsgi:application
```

Test:

```bash
curl http://127.0.0.1:8000/api/health
```

## 8. Create a systemd service

Create:

```bash
sudo nano /etc/systemd/system/swiftcart.service
```

Paste:

```ini
[Unit]
Description=SwiftCart Gunicorn Service
After=network.target

[Service]
User=%i
Group=www-data
WorkingDirectory=/var/www/swiftcart
EnvironmentFile=/var/www/swiftcart/.env
ExecStart=/var/www/swiftcart/.venv/bin/gunicorn -c /var/www/swiftcart/gunicorn.conf.py wsgi:application
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Reload and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable swiftcart.service
sudo systemctl start swiftcart.service
sudo systemctl status swiftcart.service
```

## 9. Configure Nginx

Create:

```bash
sudo nano /etc/nginx/sites-available/swiftcart
```

Paste:

```nginx
server {
    listen 80;
    server_name your-domain-or-server-ip;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable it:

```bash
sudo ln -s /etc/nginx/sites-available/swiftcart /etc/nginx/sites-enabled/swiftcart
sudo nginx -t
sudo systemctl restart nginx
```

## 10. Optional HTTPS with Let's Encrypt

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

## 11. Recommended settings for around 200 users

- 2 to 4 vCPU
- 4 to 8 GB RAM
- PostgreSQL on the same server is okay for a small launch
- Gunicorn workers: `4`
- Gunicorn threads: `2`
- Put Nginx in front of Gunicorn
- Keep uploaded images small

## 12. Notes

- SQLite is okay for local demo use, not for 200 concurrent users.
- PostgreSQL is the correct next step for multi-user production traffic.
- The app already has a health endpoint at `/api/health`.
- Profile uploads are stored inside `frontend/uploads/profiles`.

## Railway quick fix

If you deploy on Railway, do not set `DATABASE_URL` to placeholder text such as
`postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME`.

Use one of these instead:

- `DATABASE_URL=${{Postgres.DATABASE_URL}}` where `Postgres` is your Railway database service name
- shared/reference variables for `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, and `PGDATABASE`

The app now supports both styles and will ignore the placeholder example if it slips into your Railway variables.
The deployment entrypoint also strips the placeholder value before Gunicorn starts, so the app can use Railway reference vars when they are available.

## 13. Quick production start summary

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
gunicorn -c gunicorn.conf.py wsgi:application
```
