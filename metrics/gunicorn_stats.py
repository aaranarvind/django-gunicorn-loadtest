"""
Gunicorn worker statistics tracker.
Collects per-worker request counts, active status, and response times.
This data is consumed by the CloudWatch publisher.
"""
import logging
import os
import threading
import time
from collections import defaultdict

import psutil

logger = logging.getLogger('metrics.gunicorn_stats')


class WorkerTracker:
    """
    Thread-safe tracker for Gunicorn worker activity.
    Each worker (identified by PID) records request start/end events.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton — all views share the same tracker instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._lock = threading.Lock()

        # Per-worker stats: { pid: { 'active': bool, 'request_count': int, ... } }
        self._workers = defaultdict(lambda: {
            'active': False,
            'request_count': 0,
            'total_response_time': 0.0,
            'last_request_time': 0,
            'current_request_start': None,
        })

        # Rolling window of recent request durations (last 100)
        self._recent_durations = []
        self._max_recent = 100

        logger.info("WorkerTracker initialized (PID: %s)", os.getpid())

    def record_request_start(self, pid: int):
        """Mark a worker as actively processing a request."""
        with self._lock:
            self._workers[pid]['active'] = True
            self._workers[pid]['current_request_start'] = time.time()
            logger.debug("Worker %s: request started", pid)

    def record_request_end(self, pid: int, elapsed: float):
        """Mark a worker as idle and record the request duration."""
        with self._lock:
            w = self._workers[pid]
            w['active'] = False
            w['request_count'] += 1
            w['total_response_time'] += elapsed
            w['last_request_time'] = time.time()
            w['current_request_start'] = None

            self._recent_durations.append(elapsed)
            if len(self._recent_durations) > self._max_recent:
                self._recent_durations = self._recent_durations[-self._max_recent:]

            logger.debug(
                "Worker %s: request completed in %.4fs (total: %d)",
                pid, elapsed, w['request_count']
            )

    def get_stats(self) -> dict:
        """
        Return a snapshot of all worker stats.
        Used by the /api/metrics/ endpoint and the CloudWatch publisher.
        """
        with self._lock:
            workers_data = {}
            active_count = 0
            total_requests = 0

            for pid, w in self._workers.items():
                # Check if the worker process is still alive
                try:
                    proc = psutil.Process(pid)
                    cpu_pct = proc.cpu_percent(interval=0)
                    mem_mb = proc.memory_info().rss / (1024 * 1024)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    cpu_pct = 0.0
                    mem_mb = 0.0

                if w['active']:
                    active_count += 1

                avg_response = (
                    w['total_response_time'] / w['request_count']
                    if w['request_count'] > 0 else 0.0
                )

                workers_data[str(pid)] = {
                    'active': w['active'],
                    'request_count': w['request_count'],
                    'avg_response_time': round(avg_response, 4),
                    'cpu_percent': round(cpu_pct, 1),
                    'memory_mb': round(mem_mb, 1),
                }
                total_requests += w['request_count']

            total_workers = len(self._workers)
            utilization = (
                (active_count / total_workers * 100)
                if total_workers > 0 else 0.0
            )

            avg_recent = (
                sum(self._recent_durations) / len(self._recent_durations)
                if self._recent_durations else 0.0
            )

            return {
                'timestamp': time.time(),
                'master_pid': os.getppid(),
                'total_workers_seen': total_workers,
                'active_workers': active_count,
                'idle_workers': total_workers - active_count,
                'utilization_percent': round(utilization, 1),
                'total_requests': total_requests,
                'avg_recent_response_time': round(avg_recent, 4),
                'workers': workers_data,
            }

    def reset(self):
        """Reset all stats. Useful for starting a new test run."""
        with self._lock:
            self._workers.clear()
            self._recent_durations.clear()
            logger.info("WorkerTracker stats reset")
