"""
uWSGI lifecycle hooks and CloudWatch metrics integration.
This module is imported by uWSGI via the `import` directive in uwsgi.ini.

It starts the CloudWatch publisher in each worker after fork.
"""
import logging
import os
import signal

logger = logging.getLogger('metrics.uwsgi_hooks')

try:
    import uwsgi
    HAS_UWSGI = True
except ImportError:
    HAS_UWSGI = False
    logger.info("uwsgi module not available (running outside uWSGI?)")


def _post_fork_handler():
    """
    Called after uWSGI forks a worker.
    Starts the CloudWatch metrics publisher in this worker.
    """
    pid = os.getpid()
    logger.info("👷 uWSGI Worker spawned: PID=%d", pid)

    # Register this worker with the tracker
    from metrics.uwsgi_stats import WorkerTracker
    tracker = WorkerTracker()
    tracker.register_worker(pid)
        from metrics.cloudwatch import get_publisher

        namespace = os.environ.get('CW_NAMESPACE', 'UWSGIWorkers')
        region = os.environ.get('AWS_DEFAULT_REGION', 'ap-south-1')
        interval = int(os.environ.get('CW_PUSH_INTERVAL', '10'))

        publisher = get_publisher(
            namespace=namespace,
            region=region,
            interval=interval,
        )
        publisher.start()
        logger.info("📊 CloudWatch publisher started in worker PID=%d", pid)
    except Exception as e:
        logger.error(
            "Failed to start CloudWatch publisher in worker PID=%d: %s",
            pid, e,
        )


if HAS_UWSGI:
    # Register the post-fork hook with uWSGI
    try:
        uwsgi.post_fork_hook = _post_fork_handler
        logger.info("✅ uWSGI post-fork hook registered")
    except AttributeError:
        # Fallback: use atexit-style approach via postfork decorator
        logger.info("Using postfork decorator approach")

        try:
            from uwsgidecorators import postfork

            @postfork
            def start_metrics():
                _post_fork_handler()
        except ImportError:
            logger.warning(
                "uwsgidecorators not available. "
                "CloudWatch publisher will start on first request instead."
            )
