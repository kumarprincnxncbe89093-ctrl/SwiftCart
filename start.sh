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
    echo "[startup] Refusing to boot in production without a persistent Postgres database configuration."
    echo "[startup] Set DATABASE_URL (or Railway/Render Postgres variables), or ALLOW_SQLITE_IN_PRODUCTION=1 to override."
    exit 1
  fi
fi

exec gunicorn -c gunicorn.conf.py wsgi:application
