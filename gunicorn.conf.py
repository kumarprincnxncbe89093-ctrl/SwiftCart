import os


bind = os.getenv("GUNICORN_BIND", f"0.0.0.0:{os.getenv('PORT', '8000')}")
# Conservative defaults keep small Railway instances from being OOM-killed.
workers = int(os.getenv("GUNICORN_WORKERS", os.getenv("WEB_CONCURRENCY", "1")))
threads = int(os.getenv("GUNICORN_THREADS", "1"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))
accesslog = "-"
errorlog = "-"
worker_tmp_dir = "/dev/shm" if os.path.exists("/dev/shm") else "/tmp"
