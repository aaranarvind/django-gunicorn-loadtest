# 🚀 Enhanced Django + uWSGI + ECS Monitoring Project

This project provides **complete visibility** into uWSGI worker and container resource utilization, with tools to identify under-utilization vs over-utilization and auto-scaling capabilities for ECS.

## 📦 What's New

This enhancement adds three powerful monitoring tools to your existing Django + uWSGI setup:

### 1. **Worker Utilization Monitor** (`metrics/monitor.py`)
Real-time dashboard showing per-worker metrics:
- Active vs idle worker count
- Worker utilization percentage
- CPU and memory per worker
- Average response time
- **Under/Over-utilization detection**
- ECS scaling recommendations

### 2. **Container Metrics Collector** (`metrics/container_metrics.py`)
Monitor container-level resources:
- CPU usage from cgroups (works with both cgroup v1 and v2)
- Memory usage and limits
- Process count and open file descriptors
- Network I/O statistics
- **Identifies if container (not workers) is the bottleneck**

### 3. **Unified Monitor** (`metrics/unified_monitor.py`)
Combined view of workers + container:
- Identifies bottlenecks (Workers vs Container)
- Auto-generates scaling recommendations
- Provides health status and actionable insights
- Works with local Docker and cloud ECS

### 4. **ECS Auto-Scaling Handler** (`metrics/ecs_scaler.py`)
Automatically scale ECS tasks based on metrics:
- Reads monitoring recommendations
- Scales up/down based on utilization patterns
- Prevents rapid oscillation (rate-limiting)
- Can be run as scheduled task or triggered by CloudWatch alarms

### 5. **CloudFormation Template** (`deploy/ecs-cloudformation.yaml`)
Complete AWS ECS stack with:
- Task definitions with monitoring enabled
- ALB for load balancing
- CloudWatch alarms and dashboard
- Auto-scaling policies
- IAM roles with proper permissions

---

## 🎯 Quick Start

### Local Development

```bash
# 1. Start your Django app with uWSGI
docker-compose up -d web

# 2. In one terminal: Watch worker metrics
python metrics/monitor.py

# 3. In another terminal: Watch container metrics
python metrics/container_metrics.py

# 4. In third terminal: Run unified monitor (recommended)
python metrics/unified_monitor.py

# 5. Generate load to see metrics change
docker-compose run --rm locust-full
```

### Production (ECS)

```bash
# 1. Build and push Docker image
docker build -t your-registry/django-app:latest .
docker push your-registry/django-app:latest

# 2. Deploy with CloudFormation
aws cloudformation create-stack \
  --stack-name django-uwsgi \
  --template-body file://deploy/ecs-cloudformation.yaml \
  --parameters \
    ParameterKey=ContainerImage \
    ParameterValue=your-registry/django-app:latest \
    ParameterKey=UWSGIProcesses,ParameterValue=5

# 3. Once deployed, monitor with:
python metrics/unified_monitor.py --url http://YOUR_ALB_DNS:8000

# 4. Auto-scaling (optional):
python metrics/ecs_scaler.py \
  --service django-uwsgi-service \
  --cluster django-uwsgi-cluster \
  --url http://YOUR_ALB_DNS:8000
```

---

## 📊 Understanding the Metrics

### Worker Utilization %
```
= (active_workers / total_workers) * 100

Healthy Range: 50-80%
  < 30% = Under-utilized (waste of resources)
  > 80% = Over-utilized (requests may queue)
  50-80% = Optimal
```

### Bottleneck Identification

The unified monitor identifies where the constraint is:

```
WORKER_BOTTLENECK
  └─ Workers 90%+ utilized
  └─ Container CPU < 50%
  → Solution: Increase worker count

CONTAINER_OVERHEAD
  └─ Workers < 30% utilized
  └─ Container CPU > 70%
  → Solution: Profile for memory leaks, reduce workers

MEMORY_CRITICAL
  └─ Container memory > 85% of limit
  → Solution: Increase ECS task memory

BALANCED_LOAD
  └─ Workers 80%+ AND Container 70%+
  → Solution: Scale up entire task
```

---

## 🛠️ Tool Details

### Monitor.py
```bash
# Live dashboard (updates every 5 seconds)
python metrics/monitor.py

# Export metrics to file
python metrics/monitor.py --output /tmp/metrics.json

# Fetch once and exit (for scripting)
python metrics/monitor.py --one-shot --output metrics.json | jq .

# Poll every 2 seconds for 10 iterations
python metrics/monitor.py --interval 2 --count 10
```

**Output Fields:**
- `status`: ✅ OPTIMAL, 📉 UNDER-SERVED, ⚠️  OVER-UTILIZED, etc.
- `utilization_percent`: (0-100)
- `active_workers`: Count of busy workers
- `avg_response_time`: Seconds
- `workers`: Per-worker breakdown (PID, CPU%, memory MB, requests)

### Container_metrics.py
```bash
# Live container monitoring
python metrics/container_metrics.py

# One-shot export
python metrics/container_metrics.py --one-shot --output container.json

# Verbose output
python metrics/container_metrics.py --verbose
```

**Output:**
- CPU: `cpu_percent` (% of allocated CPU)
- Memory: `usage_percent` (% of limit)
- Processes: `total_processes`, `fd_utilization_percent`
- Network: RX/TX bytes and MB

### Unified_monitor.py
```bash
# Combined worker + container view (recommended)
python metrics/unified_monitor.py

# Export to file and trigger scaling
python metrics/unified_monitor.py --output analysis.json --interval 10 &
python metrics/ecs_scaler.py analysis.json
```

**Output:**
- Combines worker_metrics and container_metrics
- Identifies bottleneck
- Generates recommendations with steps
- Overall health status

### Ecs_scaler.py
```bash
# Auto-scale based on current metrics
python metrics/ecs_scaler.py \
  --service django-uwsgi-service \
  --cluster django-uwsgi-cluster

# Or with explicit analysis file
python metrics/ecs_scaler.py analysis.json \
  --service django-uwsgi-service \
  --cluster django-uwsgi-cluster

# Dry-run (see what would happen)
python metrics/ecs_scaler.py \
  --service django-uwsgi-service \
  --cluster django-uwsgi-cluster \
  --dry-run
```

---

## 🔍 Real-World Examples

### Example 1: Slow Requests

**Symptoms:**
- Response time > 5 seconds
- Utilization at 95%

**Diagnosis:**
```bash
python metrics/monitor.py
# Shows: status=⚠️  OVER-UTILIZED, utilization_percent=95

python metrics/container_metrics.py
# Shows: cpu_percent=45% (has headroom)
```

**Action:**
```bash
# Bottleneck is workers, not container
# Scale up workers in docker-compose.yml:
# Change UWSGI_PROCESSES=5 → UWSGI_PROCESSES=10

# Or trigger auto-scaling:
python metrics/ecs_scaler.py --service django-uwsgi-service ...
```

### Example 2: Wasted Resources

**Symptoms:**
- Utilization at 15%
- High memory usage
- Container CPU at 60%

**Diagnosis:**
```bash
python metrics/unified_monitor.py
# Shows: bottleneck=⚠️  CONTAINER_OVERHEAD
# Shows: workers only 15% utilized but container CPU high
```

**Action:**
```bash
# Container overhead suggests memory usage is the issue
# Options:
# 1. Profile for memory leaks: python -m memory_profiler
# 2. Reduce worker count
# 3. Check for circular imports in Django settings
```

---

## 📈 Integration with CloudWatch

The existing CloudWatch publisher already sends metrics. This monitoring stack complements it:

- **CloudWatch**: Historical data, trends, long-term analysis
- **These Monitors**: Real-time diagnostics, immediate bottleneck identification

### View CloudWatch Metrics
```bash
aws cloudwatch get-metric-statistics \
  --namespace UWSGIWorkers \
  --metric-name WorkerUtilization \
  --start-time 2024-03-13T00:00:00Z \
  --end-time 2024-03-13T23:59:59Z \
  --period 300 \
  --statistics Average,Maximum,Minimum
```

---

## 🚀 Deployment to AWS ECS

### Option 1: CloudFormation (Recommended)
```bash
# Deploy entire stack (VPC, ECS, ALB, monitoring)
aws cloudformation create-stack \
  --stack-name django-uwsgi \
  --template-body file://deploy/ecs-cloudformation.yaml \
  --parameters \
    ParameterKey=ContainerImage,ParameterValue=YOUR_IMAGE_URI \
    ParameterKey=UWSGIProcesses,ParameterValue=5 \
    ParameterKey=DesiredCount,ParameterValue=2

# Outputs:
# - LoadBalancerDNS: Your app URL
# - DashboardURL: CloudWatch dashboard
```

### Option 2: Manual ECS Setup
1. Create ECR repository
2. Push Docker image
3. Manually create ECS cluster/service
4. Update task definition with environment variables
5. Run monitoring scripts against your ALB DNS

---

## 📋 Configuration Guide

### uWSGI Settings (`uwsgi.ini`)
```ini
processes = 5       # Workers - adjust based on monitoring
threads = 1         # 1 for CPU-bound, >1 for I/O-bound
max-requests = 1000 # Restart worker after N requests (prevent leaks)
harakiri = 120      # Kill worker if request > 120s
```

### Environment Variables (`.env` or ECS task definition)
```bash
UWSGI_PROCESSES=5              # Number of worker processes
UWSGI_THREADS=1                # Threads per worker
CW_NAMESPACE=UWSGIWorkers      # CloudWatch namespace
CW_PUSH_INTERVAL=10            # Push metrics every 10s
CLOUDWATCH_ENABLED=True        # Enable CloudWatch integration
AWS_DEFAULT_REGION=ap-south-1  # Your region
```

### ECS Task Memory Sizing
```
Formula: memory_mb = 200 (Django) + (workers * 200) + 100 (buffer)

Examples:
  5 workers  → 1.2 GB (1024 MB)
  10 workers → 2.2 GB (2048 MB)
  20 workers → 4.2 GB (4096 MB)
```

---

## 🔐 Security Considerations

### IAM Permissions (ECS)
Required permissions for task role:
```json
{
  "Effect": "Allow",
  "Action": [
    "cloudwatch:PutMetricData"
  ],
  "Resource": "*"
}
```

### Network
- Metrics endpoint `/api/metrics/` is unauth (consider adding auth)
- Stats server port 9191 exposed (restrict with security groups)
- ALB handles public HTTP traffic

### Credentials
- AWS credentials passed via task execution role (not hardcoded)
- No credentials in environment variables
- Use IAM roles for EC2 instances

---

## 📚 Full Documentation

See [MONITORING_GUIDE.md](./MONITORING_GUIDE.md) for:
- Detailed tool reference
- Advanced usage examples
- Troubleshooting guide
- Integration patterns
- Best practices

---

## 🐛 Troubleshooting

### "Failed to fetch metrics"
```bash
# Check Django is running
curl http://localhost:8000/api/health/

# Check logs
docker-compose logs web

# Verify /api/metrics endpoint
curl http://localhost:8000/api/metrics/ | jq .
```

### Container metrics not available
```bash
# Container metrics require Linux/Docker
# On Mac, they won't work locally but will work in real containers

# Test: Check if /proc/stat exists
ls /proc/stat
# If not available, worker metrics still work
```

### High memory but low utilization
```bash
# Profile for leaks
python -m memory_profiler manage.py runuwsgi

# Check worker startup memory
ps aux | grep uwsgi
# Look at the RES column

# Check for issues in Django startup
django-admin shell  # Check for import side-effects
```

---

## 📞 Support

For issues or questions:
1. Check [MONITORING_GUIDE.md](./MONITORING_GUIDE.md)
2. Review tool source code (well-commented)
3. Check CloudWatch logs in AWS console
4. Run with `--verbose` or `--dry-run` flags

---

## 🎓 Key Learning Points

This project demonstrates:
- **Real-time monitoring** of application metrics
- **Resource bottleneck identification** (workers vs container)
- **Auto-scaling intelligence** based on patterns
- **CloudWatch integration** for historical analysis
- **ECS best practices** for containerized Python apps
- **Observability patterns** for micro-services

---

## 📝 Files Added/Modified

### New Files
- `metrics/monitor.py` - Worker utilization monitor
- `metrics/container_metrics.py` - Container metrics collector
- `metrics/unified_monitor.py` - Combined monitoring dashboard
- `metrics/ecs_scaler.py` - ECS auto-scaler
- `deploy/ecs-cloudformation.yaml` - CloudFormation template
- `MONITORING_GUIDE.md` - Detailed guide

### Modified Files
- `requirements.txt` - Added `requests` library

---

## 🚀 Next Steps

1. **Try it locally**:
   ```bash
   docker-compose up -d web
   python metrics/monitor.py
   ```

2. **Generate load**:
   ```bash
   docker-compose run --rm locust-full
   ```

3. **Watch metrics change**:
   - See utilization increase with load
   - See CPU/memory per worker
   - Observe response time trends

4. **Deploy to AWS**:
   - Build Docker image
   - Push to ECR
   - Deploy with CloudFormation template
   - Set up auto-scaling

5. **Configure alerts**:
   - CloudWatch alarms in CloudFormation
   - SNS notifications to your email
   - Custom thresholds based on your SLA

---

**Happy Monitoring! 📊🚀**

This enhanced monitoring stack gives you complete visibility into your Django + uWSGI deployment, from localhost development to AWS ECS production.
