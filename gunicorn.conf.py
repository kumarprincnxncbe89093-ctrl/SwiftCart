import os


def _env_int(name: str, default: int) -> int:
    raw_value = str(os.getenv(name, str(default))).strip()
    try:
        return int(raw_value)
    except ValueError:
        return default


bind = os.getenv("GUNICORN_BIND", f"0.0.0.0:{os.getenv('PORT', '8000')}")
workers = _env_int("GUNICORN_WORKERS", _env_int("WEB_CONCURRENCY", 1))
threads = _env_int("GUNICORN_THREADS", 2)
timeout = _env_int("GUNICORN_TIMEOUT", 120)
graceful_timeout = _env_int("GUNICORN_GRACEFUL_TIMEOUT", 30)
keepalive = _env_int("GUNICORN_KEEPALIVE", 5)
accesslog = "-"
errorlog = "-"
worker_tmp_dir = "/dev/shm" if os.path.exists("/dev/shm") else "/tmp"
