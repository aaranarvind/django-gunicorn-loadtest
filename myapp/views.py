"""
Views for the mock Django application.
Each endpoint simulates a different type of workload to stress uWSGI workers.
"""
import hashlib
import json
import math
import os
import random
import time

from django.http import JsonResponse

from metrics.uwsgi_stats import WorkerTracker

# Global worker tracker instance
tracker = WorkerTracker()


def health_check(request):
    """Instant health check — no processing, just confirms the server is alive."""
    return JsonResponse({
        'status': 'healthy',
        'pid': os.getpid(),
        'timestamp': time.time(),
    })


def cpu_heavy(request):
    """
    CPU-bound endpoint.
    Computes prime numbers and hash chains to keep the CPU busy.
    Query params:
        - intensity: 1-10 (default 5) — controls how much CPU work is done
    """
    intensity = min(int(request.GET.get('intensity', 5)), 10)
    pid = os.getpid()

    tracker.record_request_start(pid)
    start_time = time.time()

    # CPU-bound work: find prime numbers up to a limit based on intensity
    limit = intensity * 5000
    primes = []
    for num in range(2, limit):
        is_prime = True
        for i in range(2, int(math.sqrt(num)) + 1):
            if num % i == 0:
                is_prime = False
                break
        if is_prime:
            primes.append(num)

    # Additional CPU: hash chain
    data = f"worker-{pid}-{time.time()}".encode()
    for _ in range(intensity * 1000):
        data = hashlib.sha256(data).digest()

    elapsed = time.time() - start_time
    tracker.record_request_end(pid, elapsed)

    return JsonResponse({
        'endpoint': 'cpu-heavy',
        'pid': pid,
        'intensity': intensity,
        'primes_found': len(primes),
        'elapsed_seconds': round(elapsed, 4),
    })


def io_heavy(request):
    """
    IO-bound endpoint.
    Simulates database queries and external API calls via sleep.
    Query params:
        - delay: seconds to sleep (default 2.0, max 10.0)
    """
    delay = min(float(request.GET.get('delay', 2.0)), 10.0)
    pid = os.getpid()

    tracker.record_request_start(pid)
    start_time = time.time()

    # Simulate multiple "DB queries" and "API calls"
    steps = random.randint(3, 6)
    per_step_delay = delay / steps
    results = []
    for i in range(steps):
        time.sleep(per_step_delay)
        results.append({
            'step': i + 1,
            'type': random.choice(['db_query', 'api_call', 'cache_lookup']),
            'latency_ms': round(per_step_delay * 1000, 1),
        })

    elapsed = time.time() - start_time
    tracker.record_request_end(pid, elapsed)

    return JsonResponse({
        'endpoint': 'io-heavy',
        'pid': pid,
        'delay_requested': delay,
        'steps': results,
        'elapsed_seconds': round(elapsed, 4),
    })


def mixed_workload(request):
    """
    Mixed CPU + IO endpoint.
    Does some computation, then waits, then computes more.
    Query params:
        - intensity: 1-10 (default 3)
        - delay: seconds (default 1.0)
    """
    intensity = min(int(request.GET.get('intensity', 3)), 10)
    delay = min(float(request.GET.get('delay', 1.0)), 5.0)
    pid = os.getpid()

    tracker.record_request_start(pid)
    start_time = time.time()

    # Phase 1: CPU work
    data = f"mixed-{pid}".encode()
    for _ in range(intensity * 500):
        data = hashlib.sha256(data).digest()

    # Phase 2: IO wait (simulated external call)
    time.sleep(delay)

    # Phase 3: More CPU work
    total = 0
    for i in range(intensity * 2000):
        total += math.sin(i) * math.cos(i)

    elapsed = time.time() - start_time
    tracker.record_request_end(pid, elapsed)

    return JsonResponse({
        'endpoint': 'mixed',
        'pid': pid,
        'intensity': intensity,
        'delay': delay,
        'computation_result': round(total, 4),
        'elapsed_seconds': round(elapsed, 4),
    })


def worker_metrics(request):
    """
    Returns current worker utilization statistics as JSON.
    Useful for debugging and real-time dashboards.
    """
    stats = tracker.get_stats()
    return JsonResponse(stats, safe=False)
