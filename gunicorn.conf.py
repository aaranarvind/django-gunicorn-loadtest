"""
Gunicorn configuration file.
Controls worker count, threads, and integrates CloudWatch metrics publishing.

Environment variables:
    GUNICORN_WORKERS  — Number of worker processes (default: 5)
    GUNICORN_THREADS  — Threads per worker (default: 1)
    GUNICORN_BIND     — Bind address (default: 0.0.0.0:8000)
"""
import logging
import multiprocessing
import os

# ---------- Server Socket ----------
bind = os.environ.get('GUNICORN_BIND', '0.0.0.0:8000')
backlog = 2048

# ---------- Worker Processes ----------
workers = int(os.environ.get('GUNICORN_WORKERS', 5))
threads = int(os.environ.get('GUNICORN_THREADS', 1))
worker_class = 'gthread'  # Threaded worker to support threads > 1
worker_connections = 1000
timeout = 120
keepalive = 2
max_requests = 1000          # Restart worker after N requests (prevent leaks)
max_requests_jitter = 50     # Random jitter to avoid all workers restarting simultaneously

# ---------- Logging ----------
accesslog = '-'
errorlog = '-'
loglevel = os.environ.get('GUNICORN_LOG_LEVEL', 'info')
access_log_format = (
    'PID:%(p)s | %(h)s %(l)s %(u)s %(t)s '
    '"%(r)s" %(s)s %(b)s "%(f)s" %(D)sμs'
)

# ---------- Server Mechanics ----------
preload_app = False  # Set False so each worker gets its own memory space
daemon = False
pidfile = None
tmp_upload_dir = None

# ---------- StatsD / Metrics ----------
# Gunicorn can push metrics to StatsD natively; we use custom hooks instead.

logger = logging.getLogger('gunicorn.conf')


def on_starting(server):
    """Called just before the master process is initialized."""
    logger.info(
        "🚀 Gunicorn starting: workers=%d, threads=%d, bind=%s",
        workers, threads, bind,
    )


def post_fork(server, worker):
    """
    Called in the worker process after it has been forked.
    Each worker starts its own CloudWatch publisher thread.
    """
    logger.info("👷 Worker spawned: PID=%d", worker.pid)

    # Start CloudWatch publisher in each worker
    # (each worker tracks its own requests)
    try:
        from metrics.cloudwatch import get_publisher

        namespace = os.environ.get('CW_NAMESPACE', 'GunicornWorkers')
        region = os.environ.get('AWS_DEFAULT_REGION', 'ap-south-1')
        interval = int(os.environ.get('CW_PUSH_INTERVAL', '10'))

        publisher = get_publisher(
            namespace=namespace,
            region=region,
            interval=interval,
        )
        publisher.start()
        logger.info(
            "📊 CloudWatch publisher started in worker PID=%d", worker.pid
        )
    except Exception as e:
        logger.error(
            "Failed to start CloudWatch publisher in worker PID=%d: %s",
            worker.pid, e,
        )


def pre_request(worker, req):
    """Called just before a worker processes the request."""
    logger.debug(
        "Worker PID=%d handling: %s %s",
        worker.pid, req.method, req.uri,
    )


def post_request(worker, req, environ, resp):
    """Called after a worker finishes processing a request."""
    logger.debug(
        "Worker PID=%d completed: %s %s -> %s",
        worker.pid, req.method, req.uri, resp.status,
    )


def worker_exit(server, worker):
    """Called when a worker process exits."""
    logger.info("💀 Worker exited: PID=%d", worker.pid)

    try:
        from metrics.cloudwatch import get_publisher
        publisher = get_publisher()
        publisher.stop()
    except Exception:
        pass


def on_exit(server):
    """Called just before exiting Gunicorn."""
    logger.info("🛑 Gunicorn shutting down")
