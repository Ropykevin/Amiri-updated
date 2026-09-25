import os

bind = os.environ.get("GUNICORN_BIND") or f"0.0.0.0:{os.environ.get('PORT', '8000')}"
proc_name = "amiri"
workers = int(os.environ.get("WEB_CONCURRENCY") or "3")
threads = int(os.environ.get("GUNICORN_THREADS") or "2")
timeout = int(os.environ.get("GUNICORN_TIMEOUT") or "60")
graceful_timeout = 30
keepalive = 5
worker_class = "gthread"
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL") or "info"
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS") or "127.0.0.1,::1"
secure_scheme_headers = {"X-FORWARDED-PROTO": "https"}
