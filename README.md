# Django + uWSGI Load Testing & CloudWatch Worker Monitoring

A complete setup to observe **uWSGI worker utilization patterns** under different loads, with metrics pushed to **AWS CloudWatch**. Uses **Podman** for containerization and includes advanced monitoring with cross-process communication fixes.

## 🎯 What This Does

- **Mock Django App** with CPU-heavy, IO-heavy, and mixed workload endpoints
- **uWSGI** WSGI server with configurable processes/threads
- **CloudWatch custom metrics** — per-worker utilization, request counts, response times
- **Locust load testing** — configurable user scenarios
- **Pre-built CloudWatch dashboard** to visualize worker patterns
- **Advanced monitoring** with container metrics and ECS scaling recommendations
- **Cross-process communication** via file-based shared storage for uWSGI workers

## 🚀 Quick Start

### 1. Prerequisites

- **Podman** (container runtime)
- **podman-compose** (orchestration)
- AWS credentials configured (`~/.aws/credentials` or environment variables)

### 2. Install Podman (macOS)

```bash
# Install Podman
brew install podman

# Initialize Podman machine
podman machine init
podman machine start

# Install podman-compose
brew install podman-compose
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your AWS credentials and settings
```

### 4. Start the App

```bash
# Set podman-compose provider
export PODMAN_COMPOSE_PROVIDER=/opt/homebrew/bin/podman-compose

# Start with 5 uWSGI processes (default)
podman-compose up --build -d web

# Verify it's running
curl http://localhost:8000/api/health/
```

### 5. Deploy CloudWatch Dashboard

```bash
aws cloudwatch put-dashboard \
  --dashboard-name UWSGIWorkers-Dashboard \
  --dashboard-body file://deploy/cloudwatch_dashboard.json \
  --region ap-south-1
```

### 6. Run Load Tests

```bash
# Interactive Locust UI (http://localhost:8089)
podman run --rm -p 8089:8089 localhost/django-gunicorn-loadtest_web:latest \
  locust -f /app/loadtest/locustfile.py \
  --host http://host.containers.internal:8000 \
  --web-host 0.0.0.0

# Or headless load test (10 users, 30 seconds)
podman run --rm -p 8089:8089 localhost/django-gunicorn-loadtest_web:latest \
  locust -f /app/loadtest/locustfile.py \
  --host http://host.containers.internal:8000 \
  --autostart --users 10 --spawn-rate 2 --run-time 30s
```

## 📊 Observing Worker Patterns

### The Experiment

| Scenario | Processes | Load | Expected Observation |
|----------|-----------|------|---------------------|
| Baseline | 5 | None | 0 active, 5 idle |
| Light Load | 5 | 10 users | 1-2 active, showing load distribution |
| Medium Load | 5 | 20 users | 3-4 active, near 80% utilization |
| Heavy Load | 5 | 50+ users | All 5 active, near 100% utilization |

### Changing Process Count

```bash
# Stop the app
podman-compose down

# Restart with different process count
UWSGI_PROCESSES=3 podman-compose up --build -d web
UWSGI_PROCESSES=10 podman-compose up --build -d web
```

### What to Look for in CloudWatch

1. **Active vs Idle Workers** — Line chart shows how many workers are busy over time
2. **Worker Utilization %** — Gauge shows what percentage of defined workers are active
3. **Response Time** — Watch it increase as workers become saturated
4. **Per-Worker Metrics** — See if load is distributed evenly across workers
5. **Total Requests** — Cumulative request count across all workers

## 🔧 Key Technical Features

### Cross-Process Communication Fix

**Problem**: uWSGI workers run in separate processes, so singleton patterns don't work for shared state.

**Solution**: File-based shared storage (`/tmp/worker_stats.json`) allows workers to coordinate:
- Each worker reads/writes to shared JSON file
- Atomic file operations prevent race conditions
- Metrics are aggregated across all worker processes

### Advanced Monitoring Stack

#### 1. Worker Utilization Monitor
```bash
# Real-time worker metrics (requires running app)
python metrics/monitor.py
```

#### 2. Container Metrics Collector
```bash
# Container CPU, memory, processes
python metrics/container_metrics.py --interval 5
```

#### 3. Unified Monitor (Recommended)
```bash
# Combined view with scaling recommendations
python metrics/unified_monitor.py --interval 10
```

#### 4. ECS Auto-Scaling
```bash
# Automatic scaling based on utilization
python metrics/ecs_scaler.py --dry-run  # Test mode
python metrics/ecs_scaler.py            # Live scaling
```

## 📁 Endpoints

### Application Endpoints

| Endpoint | Type | Description |
|----------|------|-------------|
| `GET /api/health/` | Instant | Health check, returns worker PID |
| `GET /api/cpu-heavy/?intensity=5` | CPU-bound | Computes primes + hash chains |
| `GET /api/io-heavy/?delay=2.0` | IO-bound | Simulates DB/API calls with sleep |
| `GET /api/mixed/?intensity=3&delay=1.0` | Mixed | CPU work + IO wait |
| `GET /api/metrics/` | Info | **Current worker utilization JSON** |

### Monitoring Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/metrics/` | Real-time worker stats (CPU, memory, requests) |
| Locust UI | `http://localhost:8089` (when running load tests) |
| uWSGI Stats | `http://localhost:9191` (uWSGI internal stats) |

### Example API Responses

**Health Check:**
```json
{"status": "healthy", "timestamp": 1642857600.123, "worker_pid": 7}
```

**Metrics (aggregated across all workers):**
```json
{
  "timestamp": 1642857600.456,
  "master_pid": 1,
  "total_workers_seen": 5,
  "active_workers": 2,
  "idle_workers": 3,
  "utilization_percent": 40.0,
  "total_requests": 127,
  "avg_recent_response_time": 0.823,
  "workers": {
    "3": {"active": true, "request_count": 45, "avg_response_time": 0.756, "cpu_percent": 15.2, "memory_mb": 58.7},
    "4": {"active": true, "request_count": 38, "avg_response_time": 0.812, "cpu_percent": 12.8, "memory_mb": 59.1},
    "5": {"active": false, "request_count": 22, "avg_response_time": 0.945, "cpu_percent": 0.0, "memory_mb": 57.3},
    "6": {"active": false, "request_count": 11, "avg_response_time": 1.023, "cpu_percent": 0.0, "memory_mb": 58.0},
    "7": {"active": false, "request_count": 11, "avg_response_time": 0.978, "cpu_percent": 0.0, "memory_mb": 57.8}
  }
}
```

## 🔧 Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `UWSGI_PROCESSES` | `5` | Number of worker processes |
| `UWSGI_THREADS` | `1` | Threads per worker (keep at 1) |
| `CW_NAMESPACE` | `UWSGIWorkers` | CloudWatch namespace |
| `CW_PUSH_INTERVAL` | `10` | Seconds between metric pushes |
| `AWS_DEFAULT_REGION` | `ap-south-1` | AWS region |
| `INSTANCE_ID` | `docker-local` | CloudWatch dimension value |
| `CLOUDWATCH_ENABLED` | `True` | Enable/disable CW publishing |
| `AWS_ACCESS_KEY_ID` | - | AWS credentials (required) |
| `AWS_SECRET_ACCESS_KEY` | - | AWS credentials (required) |

### Podman Configuration

**Machine Setup:**
```bash
# Initialize Podman machine (one-time)
podman machine init
podman machine start

# Set compose provider
export PODMAN_COMPOSE_PROVIDER=/opt/homebrew/bin/podman-compose
```

**Networking Notes:**
- Use `host.containers.internal` for container-to-host communication
- Podman machine may need restarts if proxy conflicts occur
- Stats server runs on port 9191 inside container

### uWSGI Configuration

**Key Settings in `uwsgi.ini`:**
```ini
[uwsgi]
# Static process/thread counts (no variable expansion)
processes = 5
threads = 1

# Master process
master = true

# Stats server for monitoring
stats = 0.0.0.0:9191
stats-http = true

# Django WSGI module
module = myapp.wsgi:application

# Post-fork hooks for metrics initialization
post-fork = metrics.uwsgi_hooks.post_fork_hook
```

**Cross-Process Communication:**
- Workers share state via `/tmp/worker_stats.json`
- File-based locking prevents race conditions
- Each worker updates its own metrics independently
- Master process aggregates data for CloudWatch

## 🏗️ Architecture

```
                    ┌─────────────────────┐
                    │  Locust Load Tester  │
                    │  (configurable users) │
                    └──────────┬──────────┘
                               │ HTTP
                    ┌──────────▼──────────┐
                    │    uWSGI Master      │
                    │  (process manager)   │
                    └──────────┬──────────┘
              ┌────────┬───────┼───────┬────────┐
              ▼        ▼       ▼       ▼        ▼
          Worker 1  Worker 2  ...  Worker N   (configurable)
              │        │       │       │        │
              └────────┴───────┴───────┘        │
                       │                        │
              ┌────────▼────────────────────────┘
              │  File-based Shared Storage       │
              │  (/tmp/worker_stats.json)        │
              └────────┬─────────────────────────┘
                       │ boto3
              ┌────────▼─────────┐
              │  AWS CloudWatch  │
              │  Custom Metrics  │
              └────────┬─────────┘
                       │
              ┌────────▼─────────┐
              │    Dashboard     │
              │  (pre-built)     │
              └──────────────────┘
```

**Key Components:**
- **Podman**: Container runtime with machine virtualization
- **uWSGI**: Multi-process WSGI server with stats server
- **File-based IPC**: Cross-process communication for worker metrics
- **CloudWatch Publisher**: Background thread pushing metrics every 10s
- **Locust**: Distributed load testing framework

## 📂 Project Structure

```
django-gunicorn-loadtest/
├── myapp/                    # Django application
│   ├── settings.py           # Config with env var overrides
│   ├── urls.py               # URL routing
│   ├── views.py              # CPU/IO/mixed endpoints
│   └── wsgi.py               # WSGI entry point
├── metrics/                  # CloudWatch & monitoring modules
│   ├── cloudwatch.py         # AWS CloudWatch publisher (background thread)
│   ├── uwsgi_stats.py       # Worker activity tracker (file-based IPC)
│   ├── uwsgi_hooks.py       # uWSGI post-fork hooks
│   ├── monitor.py            # Real-time worker utilization monitor
│   ├── container_metrics.py  # Container resource metrics
│   ├── unified_monitor.py    # Combined monitoring + recommendations
│   ├── ecs_scaler.py         # ECS auto-scaling handler
│   └── __init__.py
├── loadtest/                 # Locust load tests
│   ├── locustfile.py         # Test definitions & scenarios
│   ├── full_load.conf        # 100 users config
│   ├── half_load.conf        # 50 users config
│   └── __pycache__/
├── deploy/                   # Deployment configurations
│   ├── cloudwatch_dashboard.json  # Pre-built dashboard
│   ├── ecs-cloudformation.yaml    # Complete ECS stack
│   ├── iam_policy.json            # CloudWatch permissions
│   └── userdata.sh                # EC2 bootstrap script
├── results/                  # Load test results (generated)
├── uwsgi.ini                 # uWSGI config + stats server
├── Dockerfile                # Multi-stage build with uWSGI
├── docker-compose.yml        # Podman-compatible compose
├── requirements.txt          # Python dependencies
├── .env                      # Environment variables (create from .env.example)
├── .env.example              # Environment template
├── README.md                 # This file
├── MONITORING_README.md      # Advanced monitoring guide
├── MONITORING_GUIDE.md       # Tool usage guide
└── __pycache__/
```

## 🔧 Advanced Monitoring Tools

### 1. Real-time Worker Monitor
```bash
# Live dashboard showing worker utilization
python metrics/monitor.py --interval 5
```

### 2. Container Metrics
```bash
# CPU, memory, processes (Linux/Docker only)
python metrics/container_metrics.py --interval 10
```

### 3. Unified Monitor (Recommended)
```bash
# Workers + container + scaling recommendations
python metrics/unified_monitor.py --interval 15
```

### 4. ECS Auto-Scaling
```bash
# Automatic scaling based on utilization
python metrics/ecs_scaler.py --cluster my-cluster --service my-service
```

## 🐛 Troubleshooting

### Podman Issues

**"proxy already running" error:**
```bash
podman machine stop && podman machine start
```

**Container networking issues:**
- Use `host.containers.internal` instead of `localhost`
- Check Podman machine status: `podman machine list`

### uWSGI Issues

**"no-workers" mode:**
- Check `uwsgi.ini` has static `processes = 5` (not variable expansion)
- Verify environment variables are passed to container

**Workers not starting:**
```bash
# Check uWSGI logs
podman logs uwsgi-web

# Check stats server
curl http://localhost:9191
```

### CloudWatch Issues

**Metrics not appearing:**
- Verify AWS credentials in `.env`
- Check IAM permissions (use `deploy/iam_policy.json`)
- Confirm region matches dashboard deployment

**File-based IPC issues:**
- Check `/tmp/worker_stats.json` exists in container
- Verify workers can write to `/tmp` directory

### Load Testing Issues

**Locust connection refused:**
- Ensure web container is running: `podman ps`
- Use correct host: `http://host.containers.internal:8000`
- Check Podman networking: `podman machine ssh` then `curl localhost:8000`

**High error rates:**
- Reduce user count/spawn rate
- Check application logs for errors
- Verify endpoints are responding: `curl localhost:8000/api/health/`

## 🔒 IAM Setup

Create an IAM policy using `deploy/iam_policy.json` and attach it to:
- Your **EC2 instance role** (if deploying to EC2)
- Your **user/role** (if running locally with `~/.aws/credentials`)

```bash
# Create the policy
aws iam create-policy \
  --policy-name UWSGICloudWatchMetrics \
  --policy-document file://deploy/iam_policy.json

# Attach to user/role (replace ACCOUNT and USER)
aws iam attach-user-policy \
  --user-name USER \
  --policy-arn arn:aws:iam::ACCOUNT:policy/UWSGICloudWatchMetrics
```

**Required Permissions:**
- `cloudwatch:PutMetricData` — Publish custom metrics
- `cloudwatch:GetMetricStatistics` — Read metrics for monitoring
- `cloudwatch:PutDashboard` — Deploy dashboard
- `cloudwatch:ListMetrics` — List available metrics

## 🚀 Deployment Options

### 1. Local Development (Podman)
```bash
# As shown in Quick Start above
export PODMAN_COMPOSE_PROVIDER=/opt/homebrew/bin/podman-compose
podman-compose up --build -d web
```

### 2. Docker Compose (Alternative)
```bash
# If you prefer Docker over Podman
docker-compose up --build -d web
```

### 3. AWS ECS (Production)
```bash
# Deploy complete stack with CloudFormation
aws cloudformation deploy \
  --template-file deploy/ecs-cloudformation.yaml \
  --stack-name uwsgi-loadtest-stack \
  --capabilities CAPABILITY_IAM
```

### 4. EC2 Instance
```bash
# Use userdata.sh for bootstrap
# Manual deployment with systemd/docker-compose
```

## 📈 CloudWatch Metrics Reference

### Published Metrics

| Metric Name | Description | Unit |
|-------------|-------------|------|
| `ActiveWorkers` | Number of busy workers | Count |
| `IdleWorkers` | Number of idle workers | Count |
| `TotalWorkersSeen` | Total configured workers | Count |
| `WorkerUtilization` | Percentage of active workers | Percent |
| `TotalRequests` | Cumulative requests across all workers | Count |
| `AvgResponseTime` | Average response time (recent) | Seconds |
| `WorkerRequestCount` | Requests per individual worker | Count |
| `WorkerCPUPercent` | CPU usage per worker | Percent |
| `WorkerMemoryMB` | Memory usage per worker | Megabytes |

### Dimensions

- **InstanceId**: `docker-local` (configurable)
- **WorkerPID**: Individual worker process ID

### Namespace
- **UWSGIWorkers** (configurable via `CW_NAMESPACE`)

## 🤝 Contributing

1. **Fork** the repository
2. **Create** a feature branch: `git checkout -b feature-name`
3. **Test** your changes with load tests
4. **Commit** your changes: `git commit -am 'Add feature'`
5. **Push** to the branch: `git push origin feature-name`
6. **Submit** a pull request

### Development Setup
```bash
# Clone and setup
git clone https://github.com/your-org/django-gunicorn-loadtest.git
cd django-gunicorn-loadtest

# Install dependencies
pip install -r requirements.txt

# Run tests
python manage.py test

# Start development server
python manage.py runserver
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **uWSGI** for the excellent WSGI server
- **Locust** for distributed load testing
- **AWS CloudWatch** for metrics and monitoring
- **Podman** for containerization
- **Django** for the web framework

---

**Happy Load Testing!** 🎯

*Monitor your uWSGI workers, optimize performance, and scale efficiently with CloudWatch insights.*
