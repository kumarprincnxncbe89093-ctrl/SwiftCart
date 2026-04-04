#!/usr/bin/env sh

set -eu

looks_like_placeholder_database_url() {
  value=$(printf "%s" "${1:-}" | tr '[:upper:]' '[:lower:]')
  case "$value" in
    '${{'*'}}'| '{{'*'}}' | *reference\ to*database_url* | *reference\ to*postgres* )
      return 0
      ;;
    *user*password*host*dbname*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

looks_like_postgres_database_url() {
  value=$(printf "%s" "${1:-}" | tr '[:upper:]' '[:lower:]')
  case "$value" in
    postgres://*|postgresql://*|postgresql+psycopg://*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

is_truthy() {
  value=$(printf "%s" "${1:-}" | tr '[:upper:]' '[:lower:]')
  case "$value" in
    1|true|yes|on)
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

if [ "${FLASK_ENV:-production}" = "production" ] && ! is_truthy "${ALLOW_SQLITE_IN_PRODUCTION:-0}"; then
  if looks_like_postgres_database_url "${DATABASE_URL:-}"; then
    :
  elif [ -n "${DATABASE_PRIVATE_URL:-}" ] || [ -n "${DATABASE_PUBLIC_URL:-}" ]; then
    :
  elif [ -n "${PGHOST:-}" ] && [ -n "${PGDATABASE:-}" ]; then
    :
  else
    echo "[startup] Warning: no persistent Postgres database configuration was detected before boot."
    echo "[startup] Continuing startup so the service can expose health details. Check /api/health for database status."
    echo "[startup] Configure DATABASE_URL (or Railway/Render Postgres variables), or set ALLOW_SQLITE_IN_PRODUCTION=1 only if you intentionally want SQLite."
  fi
fi

exec gunicorn -c gunicorn.conf.py wsgi:application
