# Screenshots Directory

This directory contains screenshots of the CloudWatch monitoring dashboard and metrics.

## Expected Screenshots

### 1. `dashboard-overview.png`
- **Description**: Full CloudWatch dashboard showing all monitoring widgets
- **When to capture**: After running a load test to show populated metrics
- **Widgets to include**:
  - Worker Utilization % (gauge)
  - Active vs Idle Workers (line chart)
  - Total Requests (counter)
  - Average Response Time (line chart)
  - Per-worker CPU and Memory usage

### 2. `worker-utilization.png`
- **Description**: Close-up of worker utilization metrics during load testing
- **When to capture**: During or immediately after a load test
- **Focus**: Show how worker utilization changes under load

### 3. `metrics-detail.png`
- **Description**: Detailed view of individual worker metrics
- **When to capture**: After load test completion
- **Focus**: Per-worker request counts, CPU usage, memory usage

## How to Generate Data for Screenshots

1. **Start the application**:
   ```bash
   export PODMAN_COMPOSE_PROVIDER=/opt/homebrew/bin/podman-compose
   podman-compose up --build -d web
   ```

2. **Run a load test**:
   ```bash
   podman run --rm -p 8089:8089 localhost/django-gunicorn-loadtest_web:latest \
     locust -f /app/loadtest/locustfile.py \
     --host http://host.containers.internal:8000 \
     --autostart --users 15 --spawn-rate 3 --run-time 30s
   ```

3. **Open CloudWatch Dashboard**:
   - URL: https://ap-south-1.console.aws.amazon.com/cloudwatch/home?region=ap-south-1#dashboards:name=UWSGIWorkerMonitoring
   - Wait 1-2 minutes for metrics to appear
   - Set time range to show the load test period

4. **Take screenshots** and save them in this directory

## Screenshot Guidelines

- **Resolution**: At least 1920x1080 for clarity
- **Format**: PNG preferred for quality
- **Naming**: Use descriptive names as listed above
- **Time Range**: Ensure the dashboard shows the load test timeframe
- **Annotations**: Consider adding arrows or labels to highlight key metrics