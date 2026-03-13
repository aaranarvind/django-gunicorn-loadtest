"""
Locust load testing file for uWSGI worker utilization testing.

Usage:
    # Full load test (saturate all workers):
    locust -f locustfile.py --config full_load.conf

    # Half load test (~50% worker utilization):
    locust -f locustfile.py --config half_load.conf

    # Custom (with web UI):
    locust -f locustfile.py --host http://localhost:8000
"""
import random

from locust import HttpUser, between, task


class HealthCheckUser(HttpUser):
    """
    Lightweight user that only hits the health endpoint.
    Used to establish baseline with minimal worker impact.
    """
    weight = 1
    wait_time = between(1, 3)

    @task
    def health(self):
        self.client.get("/api/health/")


class CPUHeavyUser(HttpUser):
    """
    User that hammers the CPU-heavy endpoint.
    This will keep workers busy with computation.
    """
    weight = 4
    wait_time = between(0.5, 2)

    @task(3)
    def cpu_medium(self):
        """Medium intensity CPU work."""
        self.client.get("/api/cpu-heavy/?intensity=5")

    @task(1)
    def cpu_high(self):
        """High intensity CPU work — will tie up a worker longer."""
        self.client.get("/api/cpu-heavy/?intensity=8")


class IOHeavyUser(HttpUser):
    """
    User that hits the IO-heavy endpoint.
    Workers block on simulated IO, so they appear 'active' but
    are really just waiting. This is great for testing threaded workers.
    """
    weight = 4
    wait_time = between(0.5, 2)

    @task(3)
    def io_medium(self):
        """Medium delay IO work."""
        self.client.get("/api/io-heavy/?delay=1.5")

    @task(1)
    def io_long(self):
        """Longer IO delay — holds worker for extended period."""
        self.client.get("/api/io-heavy/?delay=3.0")


class MixedWorkloadUser(HttpUser):
    """
    User that exercises the mixed CPU+IO endpoint.
    More realistic: some compute, some waiting.
    """
    weight = 2
    wait_time = between(1, 3)

    @task(2)
    def mixed_default(self):
        """Default mixed workload."""
        self.client.get("/api/mixed/")

    @task(1)
    def mixed_heavy(self):
        """Heavy mixed workload — more CPU + longer IO wait."""
        self.client.get("/api/mixed/?intensity=7&delay=2.0")

    @task(1)
    def check_metrics(self):
        """Periodically check the metrics endpoint."""
        with self.client.get("/api/metrics/", catch_response=True) as response:
            if response.status_code == 200:
                data = response.json()
                # Tag the response with worker utilization for Locust reporting
                response.success()
            else:
                response.failure(f"Metrics endpoint returned {response.status_code}")
