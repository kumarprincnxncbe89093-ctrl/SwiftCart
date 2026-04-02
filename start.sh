#!/usr/bin/env sh

set -eu

looks_like_placeholder_database_url() {
  value=$(printf "%s" "${1:-}" | tr '[:upper:]' '[:lower:]')
  case "$value" in
    *user*password*host*dbname*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

if [ -n "${DATABASE_URL:-}" ] && looks_like_placeholder_database_url "${DATABASE_URL}"; then
  echo "[startup] Ignoring placeholder DATABASE_URL and falling back to Railway reference vars."
  unset DATABASE_URL
fi

if [ -n "${DATABASE_PRIVATE_URL:-}" ]; then
  echo "[startup] Using DATABASE_PRIVATE_URL from the platform environment."
elif [ -n "${DATABASE_PUBLIC_URL:-}" ]; then
  echo "[startup] Using DATABASE_PUBLIC_URL from the platform environment."
elif [ -n "${PGHOST:-}" ] && [ -n "${PGDATABASE:-}" ]; then
  echo "[startup] Using PGHOST/PGDATABASE Railway variables."
else
  echo "[startup] No Postgres reference variables detected. The app may fall back to SQLite."
fi

exec gunicorn -c gunicorn.conf.py wsgi:application
