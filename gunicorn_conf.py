"""
MedGuide AI — Enterprise Gunicorn Production Process Configuration.

Configured for high-concurrency 1 Million+ user deployments on AWS EKS / Ubuntu.
Uses Uvicorn's asynchronous worker (`uvicorn.workers.UvicornWorker`) to handle
thousands of simultaneous streaming SSE connections per pod.
"""

import multiprocessing
import os

# Server socket
bind = os.environ.get("BIND", "0.0.0.0:8000")
backlog = 2048

# Worker processes
# At 1M scale on Kubernetes, 2-4 workers per pod is ideal to maximize CPU efficiency
default_workers = max(2, multiprocessing.cpu_count())
workers = int(os.environ.get("WEB_CONCURRENCY", default_workers))
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000

# Worker lifecycle & memory protection
# Jittered max requests prevent memory leaks without all workers recycling simultaneously
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", 1500))
max_requests_jitter = int(os.environ.get("GUNICORN_JITTER", 200))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 90))
keepalive = int(os.environ.get("GUNICORN_KEEPALIVE", 15))
graceful_timeout = 30

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)sµs'

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None
preload_app = False  # Keep False when using connection pools to avoid shared fork state
