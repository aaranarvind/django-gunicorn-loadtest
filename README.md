# Django + uWSGI Load Testing & CloudWatch Worker Monitoring

A complete setup to observe **uWSGI worker utilization patterns** under different loads, with metrics pushed to **AWS CloudWatch**.

## 🎯 What This Does

- **Mock Django App** with CPU-heavy, IO-heavy, and mixed workload endpoints
- **uWSGI** WSGI server with configurable processes/threads
- **CloudWatch custom metrics** — per-worker utilization, request counts, response times
- **Locust load testing** — full load (100 users) and half load (50 users)
- **Pre-built CloudWatch dashboard** to visualize worker patterns

## 🚀 Quick Start

### 1. Prerequisites

- Docker & Docker Compose
- AWS credentials configured (`~/.aws/credentials` or env vars)

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your settings
```

### 3. Start the App

```bash
# Start with 5 uWSGI processes (default)
docker-compose up --build -d web

# Verify it's running
curl http://localhost:8000/api/health/
```

### 4. Deploy CloudWatch Dashboard

```bash
aws cloudwatch put-dashboard \
  --dashboard-name UWSGIWorkerMonitoring \
  --dashboard-body file://deploy/cloudwatch_dashboard.json \
  --region ap-south-1
```

### 5. Run Load Tests

```bash
# Option A: Interactive Locust UI (http://localhost:8089)
docker-compose --profile loadtest up locust

# Option B: Headless half-load test (50 users, 5 min)
docker-compose --profile halfload up locust-half

# Option C: Headless full-load test (100 users, 5 min)
docker-compose --profile fullload up locust-full
```

## 📊 Observing Worker Patterns

### The Experiment

| Scenario | Processes | Load | Expected Observation |
|----------|-----------|------|---------------------|
| Baseline | 5 | None | 0 active, 5 idle |
| Half Load | 5 | 50 users | 2-3 active, showing uneven distribution |
| Full Load | 5 | 100 users | All 5 active, near 100% utilization |
| Scale Up | 10 | 100 users | Workers spread out, lower per-worker utilization |

### Changing Process Count

```bash
# Stop the app
docker-compose down

# Restart with different process count
UWSGI_PROCESSES=1 docker-compose up --build -d web
UWSGI_PROCESSES=3 docker-compose up --build -d web
UWSGI_PROCESSES=10 docker-compose up --build -d web
```

### What to Look for in CloudWatch

1. **Active vs Idle Workers** — Line chart shows how many workers are busy over time
2. **Worker Utilization %** — Gauge shows what percentage of defined workers are active
3. **Response Time** — Watch it increase as workers become saturated
4. **Per-Worker Metrics** — See if load is distributed evenly or if some workers handle more

## 📁 Endpoints

| Endpoint | Type | Description |
|----------|------|-------------|
| `GET /api/health/` | Instant | Health check, returns PID |
| `GET /api/cpu-heavy/?intensity=5` | CPU-bound | Computes primes + hash chains |
| `GET /api/io-heavy/?delay=2.0` | IO-bound | Simulates DB/API calls |
| `GET /api/mixed/?intensity=3&delay=1.0` | Mixed | CPU work + IO wait |
| `GET /api/metrics/` | Info | Current worker utilization JSON |

## 🔧 Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `UWSGI_PROCESSES` | `5` | Number of worker processes |
| `UWSGI_THREADS` | `1` | Threads per worker |
| `CW_NAMESPACE` | `UWSGIWorkers` | CloudWatch namespace |
| `CW_PUSH_INTERVAL` | `10` | Seconds between metric pushes |
| `AWS_DEFAULT_REGION` | `ap-south-1` | AWS region |
| `INSTANCE_ID` | `docker-local` | CloudWatch dimension value |
| `CLOUDWATCH_ENABLED` | `True` | Enable/disable CW publishing |

## 🏗️ Architecture

```
                    ┌─────────────────────┐
                    │  Locust Load Tester  │
                    │  (50 or 100 users)   │
                    └──────────┬──────────┘
                               │ HTTP
                    ┌──────────▼──────────┐
                    │    uWSGI Master      │
                    │  (process manager)   │
                    └──────────┬──────────┘
              ┌────────┬───────┼───────┬────────┐
              ▼        ▼       ▼       ▼        ▼
          Worker 1  Worker 2  ...  Worker N   (configurable)
              │        │       │       │
              └────────┴───────┴───────┘
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

## 📂 Project Structure

```
django-uwsgi-loadtest/
├── myapp/                    # Django application
│   ├── settings.py           # Config with env var overrides
│   ├── urls.py               # URL routing
│   ├── views.py              # CPU/IO/mixed endpoints
│   └── wsgi.py               # WSGI entry point
├── metrics/                  # CloudWatch metrics module
│   ├── cloudwatch.py         # AWS CloudWatch publisher
│   ├── uwsgi_stats.py       # Worker activity tracker
│   └── uwsgi_hooks.py       # uWSGI post-fork hooks
├── loadtest/                 # Locust load tests
│   ├── locustfile.py         # Test definitions
│   ├── full_load.conf        # 100 users config
│   └── half_load.conf        # 50 users config
├── deploy/                   # Deployment configs
│   ├── cloudwatch_dashboard.json
│   ├── iam_policy.json
│   └── userdata.sh           # EC2 bootstrap
├── uwsgi.ini                 # uWSGI config + stats server
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## 🔒 IAM Setup

Create an IAM policy using `deploy/iam_policy.json` and attach it to:
- Your **EC2 instance role** (if deploying to EC2)
- Your **user/role** (if running locally with `~/.aws/credentials`)

```bash
aws iam create-policy \
  --policy-name UWSGICloudWatchMetrics \
  --policy-document file://deploy/iam_policy.json
```
