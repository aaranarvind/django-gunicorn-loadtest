# 📊 MONITORING GUIDE: uWSGI Worker & Container Utilization

This guide explains how to use the three monitoring tools to track worker and container health in your Django + uWSGI + ECS setup.

## 🎯 QuickStart

### 1. Run the Application
```bash
docker-compose up -d web
# or
UWSGI_PROCESSES=5 python manage.py runuwsgi
```

### 2. Start Monitoring (Real-time Dashboard)
```bash
# Live worker metrics dashboard (updates every 5 seconds)
python metrics/monitor.py

# Or with custom interval
python metrics/monitor.py --interval 2 --count 30
```

### 3. In Another Terminal, View Container Metrics
```bash
# Container CPU, memory, processes (requires Linux or Docker)
python metrics/container_metrics.py --interval 5
```

### 4. Unified Dashboard (Recommended)
```bash
# Single view of workers + container + recommendations
python metrics/unified_monitor.py --interval 10
```

---

## 🛠️ Tool Reference

### Tool 1: Worker Utilization Monitor (`monitor.py`)

**What it does:**
- Fetches metrics from `/api/metrics/` endpoint
- Shows per-worker stats (CPU, memory, request count, response time)
- Identifies under-utilized vs over-utilized workers
- Provides ECS scaling recommendations

**Usage:**
```bash
# Real-time live dashboard
python metrics/monitor.py

# Fetch once (for scripting/integration)
python metrics/monitor.py --one-shot --output metrics.json

# Custom update interval and limit iterations
python metrics/monitor.py --interval 2 --count 60

# Run against remote server
python metrics/monitor.py --url http://prod-server.example.com:8000
```

**Output Includes:**
- Worker utilization percentage
- Number of active vs idle workers
- Per-worker breakdown (PID, requests, response time, CPU%, memory)
- Status indicator:
  - ✅ OPTIMAL (50-80% utilization)
  - 📉 UNDER-SERVED (<50%)
  - ⚠️  OVER-UTILIZED (>80%)

**Classification Logic:**
```
Under-Utilized:   < 30% → Scale down (reduce workers or container resources)
Under-Served:    30-50% → Monitor, capacity available
Optimal:         50-80% → Healthy balance
Over-Utilized:   > 80%  → Scale up (increase workers or container resources)
```

### Tool 2: Container Metrics Collector (`container_metrics.py`)

**What it does:**
- Monitors container-level resources from cgroups
- Tracks CPU, memory, disk I/O, network, process count
- Detects cgroup v1 vs v2 (works on any Docker/ECS container)
- Shows open file descriptor usage

**Usage:**
```bash
# Live container metrics
python metrics/container_metrics.py

# One-shot with output file
python metrics/container_metrics.py --one-shot --output container.json

# Run once and exit (useful for cron jobs)
python metrics/container_metrics.py --one-shot
```

**Why This Matters:**
- Shows if the **container** is the bottleneck (high CPU/memory despite low worker util)
- Helps identify resource contention
- Tracks network I/O for ECS cost analysis
- Monitors file descriptor limits

**Metrics:**
```
CPU:            % of allocated CPU quota
Memory:         MB used / limit, percentage
Processes:      Total process count, FD utilization%
Network:        RX/TX bytes (useful for pricing)
```

### Tool 3: Unified Monitor (`unified_monitor.py`)

**What it does:**
- Combines worker + container metrics in ONE view
- Identifies bottlenecks (workers vs container)
- Auto-generates ECS scaling recommendations
- Determines overall system health

**Usage:**
```bash
# Unified monitoring with auto-recommendations
python metrics/unified_monitor.py

# Export to file for dashboards/alerting
python metrics/unified_monitor.py --output analysis.json --interval 10
```

**Bottleneck Classification:**
```
✅ HEALTHY                    → All systems operating normally
⚠️  WORKER_BOTTLENECK        → Workers maxed out, container has headroom
⚠️  CONTAINER_OVERHEAD       → Container CPU high, workers idle
🟠 BALANCED_LOAD            → Both heavily utilized
🔴 MEMORY_CRITICAL          → Container memory near limit
```

**Recommendations Generated:**
- SCALE_UP_WORKERS: When workers busy but container has CPU/memory
- REDUCE_WORKER_COUNT: When workers idle but container CPU high
- INCREASE_MEMORY: When memory near limit
- MAINTAIN: When operating at optimal levels

---

## 📈 Real-World Scenarios

### Scenario 1: Slow Requests, Increasing Response Time
```bash
# Run worker monitor while load testing
python metrics/monitor.py

# Expected findings:
# - High avg_response_time (>5s)
# - utilization_percent > 90%
# - Many workers marked as "ACTIVE"

# Recommendation: Scale up workers or container resources
```

### Scenario 2: Container Using High CPU Despite Few Requests
```bash
# Run unified monitor
python metrics/unified_monitor.py

# If you see:
# - worker utilization < 30%
# - container CPU > 70%
# - bottleneck: "CONTAINER_OVERHEAD"

# Action: Check for:
# - Memory leaks in workers
# - Background processes
# - Heavy imports at startup
# - uWSGI memory usage
```

### Scenario 3: Memory Pressure in Container
```bash
# Watch container metrics
python metrics/container_metrics.py

# If memory usage_percent > 85%:
# Option 1: Increase ECS task memory
# Option 2: Reduce UWSGI_PROCESSES
# Option 3: Profile for leaks: python -m memory_profiler
```

---

## 🔌 Integration Examples

### With CloudWatch Dashboards
```bash
# Start monitor with JSON export
python metrics/unified_monitor.py --output /tmp/metrics.json --interval 10 &

# Watch file and push to CloudWatch (pseudo-code)
watch -n 10 'python push_to_cloudwatch.py /tmp/metrics.json'
```

### With Docker-Compose
```bash
# Start all services including monitoring
docker-compose up -d
docker-compose exec web python metrics/monitor.py --count 100 --interval 5
```

### With Kubernetes
```bash
# Run as sidecar container
kubectl exec -it deployment/django-app -c web \
  python metrics/unified_monitor.py --output /dev/stdout
```

### With Shell Scripts / Cron
```bash
#!/bin/bash
# Monitor and auto-scale
python metrics/unified_monitor.py --one-shot --output /tmp/health.json
python scale_handler.py /tmp/health.json
# Parses recommendations and adjusts ECS task count
```

---

## 🚀 ECS Deployment Recommendations

### Docker-Compose Configuration
```yaml
services:
  web:
    environment:
      # Adjust these based on recommendations
      UWSGI_PROCESSES: 5      # Increase if worker-bottleneck
      UWSGI_THREADS: 1        # Usually 1, unless I/O bound
    # Set memory/CPU quota for container
    # This limits total container resources
```

### ECS Task Definition
```json
{
  "memory": 1024,           // MB - increase if memory-critical
  "cpu": 512,               // CPU units (256 = 0.25 CPU)
  "containerDefinitions": {
    "environment": [
      {
        "name": "UWSGI_PROCESSES",
        "value": "5"         // Adjust based on monitoring
      }
    ]
  }
}
```

**Memory Sizing Guide:**
```
Base Django: ~200 MB
Per worker: ~150-250 MB (depends on imports)
Buffer: ~100 MB (OS, caches)

Formula: Memory = 200 + (UWSGI_PROCESSES * 200) + 100
Examples:
  5 workers  → 1.2 GB recommended
  10 workers → 2.2 GB recommended
  20 workers → 4.2 GB recommended
```

---

## 📊 Understanding the Metrics

### Worker Utilization Percent
```
= (active_workers / total_workers) * 100

50%  = 2 of 4 workers active
100% = All workers busy
0%   = All workers idle

Healthy: 50-80%
```

### Response Time Trends
```
Increasing → Workers getting slower (CPU contention or memory pressure)
Stable     → Healthy load
Spiking    → Temporary surge (normal)

Action: If avg > 5s, scale up
```

### CPU Usage (Container)
```
Cgroup limits: Set via docker memory/cpu flags
High CPU with low worker util → Container overhead, profiling needed
High CPU with high worker util → Scale up container size
```

### Memory Usage
```
Monitor: current_mb / limit_mb
Crisis: > 90% (approaching OOM kill)
Warning: > 80%
Safe: < 70%

Linux will kill processes if memory exceeded - proactive scaling important!
```

---

## 🔧 Troubleshooting

### "Failed to fetch metrics" Error
```bash
# Problem: /api/metrics/ endpoint not responding
# Solution:
1. Check Django is running: curl http://localhost:8000/api/health/
2. Check metrics middleware is loaded
3. Verify no errors in Django logs: docker-compose logs web
```

### "cgroup info not available"
```bash
# Problem: Not running in Docker or cgroups disabled
# Solution:
# Container metrics won't work, but worker metrics still work
# This is fine for development
```

### High Memory But Utilization Normal
```bash
# Problem: Memory leaks or large imports
# Solution:
# 1. Check worker process startup: top -p <worker-pid>
# 2. Profile with: python -m memory_profiler
# 3. Check for circular imports or static data structures
```

### All Workers IDLE but Requests Queued
```bash
# Problem: Worker deadlock or hangs
# Solution:
# 1. Check harakiri timeout in uwsgi.ini
# 2. Increase timeout if legitimate long-running tasks
# 3. Kill and restart: docker restart <container>
```

---

## 📚 CloudWatch Integration

The existing CloudWatch publisher already sends metrics. To view them:

```bash
# AWS CLI - list your metrics
aws cloudwatch list-metrics --namespace UWSGIWorkers

# View specific metric
aws cloudwatch get-metric-statistics \
  --namespace UWSGIWorkers \
  --metric-name WorkerUtilization \
  --start-time 2024-03-13T00:00:00Z \
  --end-time 2024-03-13T23:59:59Z \
  --period 300 \
  --statistics Average,Maximum
```

### Dashboard Configuration in AWS Console
1. Go to CloudWatch → Dashboards → Create Dashboard
2. Add widgets for:
   - ActiveWorkers (line chart)
   - WorkerUtilization (gauge)
   - AvgResponseTime (line chart)
   - Per-worker CPU/Memory (heatmap)

---

## 🎯 Monitoring Checklist

Use this daily/weekly:

- [ ] Check worker utilization (should be 50-80%)
- [ ] Monitor response times (should be consistent)
- [ ] Check container CPU/memory (should have 20% headroom)
- [ ] Review CloudWatch dashboard for trends
- [ ] Verify no workers in "error" state
- [ ] Check for memory growth over time (leak detection)
- [ ] Review slow query logs if response time spike

---

## 📞 Support & Questions

**Q: How many workers should I use?**
A: Start with `CPU_CORES * 2` to `CPU_CORES * 4`. Adjust based on monitoring. More workers = more memory usage.

**Q: When to use threads vs processes?**
A: Use processes (threads=1) for CPU-bound work. Use threads for I/O-bound (DB, API calls).

**Q: How often to update monitoring?**
A: Every 5-10 seconds for live monitoring. Every 60s for production alerts.

**Q: Is CloudWatch enough?**
A: CloudWatch is good for historical analysis. Use these monitors for real-time diagnostics.

---

**Happy Monitoring! 🚀**

Questions? Check the metrics source code or Django logs.
