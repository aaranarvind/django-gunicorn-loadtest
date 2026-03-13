"""
CloudWatch metrics publisher.
Pushes uWSGI worker utilization metrics to AWS CloudWatch
at a configurable interval using a background daemon thread.
"""
import logging
import os
import threading
import time

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from metrics.uwsgi_stats import WorkerTracker

logger = logging.getLogger('metrics.cloudwatch')


class CloudWatchPublisher:
    """
    Background thread that periodically pushes worker metrics to CloudWatch.
    Metrics are published under the namespace configured in Django settings.
    """

    def __init__(
        self,
        namespace: str = 'UWSGIWorkers',
        region: str = 'ap-south-1',
        interval: int = 10,
        instance_id: str = None,
    ):
        self.namespace = namespace
        self.region = region
        self.interval = interval
        self.instance_id = instance_id or os.environ.get('INSTANCE_ID', 'local')
        self.tracker = WorkerTracker()
        self._stop_event = threading.Event()
        self._thread = None

        try:
            self.client = boto3.client(
                'cloudwatch',
                region_name=self.region,
            )
            logger.info(
                "CloudWatch client initialized (namespace=%s, region=%s)",
                self.namespace, self.region
            )
        except NoCredentialsError:
            logger.warning(
                "AWS credentials not found. CloudWatch publishing disabled. "
                "Metrics will still be logged to console."
            )
            self.client = None

    def start(self):
        """Start the background metrics publishing thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("CloudWatch publisher already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._publish_loop,
            daemon=True,
            name='cloudwatch-publisher',
        )
        self._thread.start()
        logger.info(
            "CloudWatch publisher started (interval=%ds, PID=%d)",
            self.interval, os.getpid()
        )

    def stop(self):
        """Stop the background publishing thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("CloudWatch publisher stopped")

    def _publish_loop(self):
        """Main loop: collect stats and publish every `interval` seconds."""
        while not self._stop_event.is_set():
            try:
                stats = self.tracker.get_stats()
                self._publish_metrics(stats)
                self._log_metrics(stats)
            except Exception as e:
                logger.error("Error publishing metrics: %s", e, exc_info=True)

            self._stop_event.wait(self.interval)

    def _publish_metrics(self, stats: dict):
        """Push metric data points to CloudWatch."""
        if not self.client:
            return

        dimensions = [
            {'Name': 'InstanceId', 'Value': self.instance_id},
        ]

        metric_data = [
            {
                'MetricName': 'ActiveWorkers',
                'Value': stats['active_workers'],
                'Unit': 'Count',
                'Dimensions': dimensions,
            },
            {
                'MetricName': 'IdleWorkers',
                'Value': stats['idle_workers'],
                'Unit': 'Count',
                'Dimensions': dimensions,
            },
            {
                'MetricName': 'TotalWorkersSeen',
                'Value': stats['total_workers_seen'],
                'Unit': 'Count',
                'Dimensions': dimensions,
            },
            {
                'MetricName': 'WorkerUtilization',
                'Value': stats['utilization_percent'],
                'Unit': 'Percent',
                'Dimensions': dimensions,
            },
            {
                'MetricName': 'TotalRequests',
                'Value': stats['total_requests'],
                'Unit': 'Count',
                'Dimensions': dimensions,
            },
            {
                'MetricName': 'AvgResponseTime',
                'Value': stats['avg_recent_response_time'],
                'Unit': 'Seconds',
                'Dimensions': dimensions,
            },
        ]

        # Add per-worker metrics
        for pid, worker_data in stats.get('workers', {}).items():
            worker_dims = dimensions + [
                {'Name': 'WorkerPID', 'Value': str(pid)},
            ]
            metric_data.extend([
                {
                    'MetricName': 'WorkerRequestCount',
                    'Value': worker_data['request_count'],
                    'Unit': 'Count',
                    'Dimensions': worker_dims,
                },
                {
                    'MetricName': 'WorkerCPUPercent',
                    'Value': worker_data['cpu_percent'],
                    'Unit': 'Percent',
                    'Dimensions': worker_dims,
                },
                {
                    'MetricName': 'WorkerMemoryMB',
                    'Value': worker_data['memory_mb'],
                    'Unit': 'Megabytes',
                    'Dimensions': worker_dims,
                },
            ])

        # CloudWatch accepts max 1000 metric data points per call;
        # batch in groups of 25 for efficiency
        batch_size = 25
        for i in range(0, len(metric_data), batch_size):
            batch = metric_data[i:i + batch_size]
            try:
                self.client.put_metric_data(
                    Namespace=self.namespace,
                    MetricData=batch,
                )
            except ClientError as e:
                logger.error("CloudWatch PutMetricData failed: %s", e)

    def _log_metrics(self, stats: dict):
        """Log metrics to console for local debugging."""
        logger.info(
            "📊 Workers: %d active / %d total (%.1f%% utilization) | "
            "Requests: %d | Avg Response: %.4fs",
            stats['active_workers'],
            stats['total_workers_seen'],
            stats['utilization_percent'],
            stats['total_requests'],
            stats['avg_recent_response_time'],
        )
        for pid, w in stats.get('workers', {}).items():
            status = "🟢 ACTIVE" if w['active'] else "⚪ IDLE"
            logger.info(
                "  Worker PID %s: %s | Requests: %d | "
                "Avg: %.4fs | CPU: %.1f%% | Mem: %.1fMB",
                pid, status, w['request_count'],
                w['avg_response_time'], w['cpu_percent'], w['memory_mb'],
            )


# Module-level publisher instance (initialized in uwsgi_hooks.py)
_publisher = None


def get_publisher(**kwargs) -> CloudWatchPublisher:
    """Get or create the singleton CloudWatch publisher."""
    global _publisher
    if _publisher is None:
        _publisher = CloudWatchPublisher(**kwargs)
    return _publisher
