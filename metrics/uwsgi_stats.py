"""
uWSGI worker statistics tracker.
Collects per-worker request counts, active status, and response times.
This data is consumed by the CloudWatch publisher.
"""
import json
import logging
import os
import threading
import time
from collections import defaultdict
from pathlib import Path

import psutil

logger = logging.getLogger('metrics.uwsgi_stats')


class WorkerTracker:
    """
    Thread-safe tracker for uWSGI worker activity.
    Uses a shared file for cross-process communication since uWSGI workers
    are separate processes and can't share memory.
    """

    _instance = None
    _lock = threading.Lock()
    _stats_file = Path('/tmp/worker_stats.json')

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
        self._pid = os.getpid()

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

        # Ensure stats file exists
        if not self._stats_file.exists():
            self._save_stats_to_file()

        logger.info("WorkerTracker initialized (PID: %s)", self._pid)

    def _load_stats_from_file(self):
        """Load stats from shared file."""
        try:
            if self._stats_file.exists():
                with open(self._stats_file, 'r') as f:
                    data = json.load(f)
                    # Convert string keys back to int for PIDs
                    self._workers = defaultdict(lambda: {
                        'active': False,
                        'request_count': 0,
                        'total_response_time': 0.0,
                        'last_request_time': 0,
                        'current_request_start': None,
                    }, {int(pid): stats for pid, stats in data.get('workers', {}).items()})
                    self._recent_durations = data.get('recent_durations', [])
        except (json.JSONDecodeError, FileNotFoundError, KeyError):
            # File corrupted or doesn't exist, start fresh
            self._workers = defaultdict(lambda: {
                'active': False,
                'request_count': 0,
                'total_response_time': 0.0,
                'last_request_time': 0,
                'current_request_start': None,
            })
            self._recent_durations = []

    def _save_stats_to_file(self):
        """Save current stats to shared file."""
        try:
            data = {
                'workers': dict(self._workers),
                'recent_durations': self._recent_durations,
                'timestamp': time.time()
            }
            with open(self._stats_file, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning("Failed to save stats to file: %s", e)

    def record_request_start(self, pid: int):
        """Mark a worker as actively processing a request."""
        with self._lock:
            # Load latest stats from file
            self._load_stats_from_file()

            self._workers[pid]['active'] = True
            self._workers[pid]['current_request_start'] = time.time()

            # Save updated stats
            self._save_stats_to_file()

            logger.debug("Worker %s: request started", pid)

    def record_request_end(self, pid: int, elapsed: float):
        """Mark a worker as idle and record the request duration."""
        with self._lock:
            # Load latest stats from file
            self._load_stats_from_file()

            w = self._workers[pid]
            w['active'] = False
            w['request_count'] += 1
            w['total_response_time'] += elapsed
            w['last_request_time'] = time.time()
            w['current_request_start'] = None

            self._recent_durations.append(elapsed)
            if len(self._recent_durations) > self._max_recent:
                self._recent_durations = self._recent_durations[-self._max_recent:]

            # Save updated stats
            self._save_stats_to_file()

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
            # Load latest stats from file
            self._load_stats_from_file()

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

            total_workers = len([pid for pid in self._workers.keys()
                               if self._is_worker_alive(pid)])

            utilization = (active_count / total_workers * 100) if total_workers > 0 else 0.0

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

    def _is_worker_alive(self, pid: int) -> bool:
        """Check if a worker process is still running."""
        try:
            os.kill(pid, 0)  # Signal 0 doesn't kill, just checks if process exists
            return True
        except OSError:
            return False

    def reset(self):
        """Reset all stats. Useful for starting a new test run."""
        with self._lock:
            self._load_stats_from_file()
            self._workers.clear()
            self._recent_durations.clear()
            self._save_stats_to_file()
            logger.info("WorkerTracker stats reset")
