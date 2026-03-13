# ---- Build Stage ----
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies for uWSGI (compiles C extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    linux-headers-generic \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Runtime Stage ----
FROM python:3.11-slim

# Install runtime dependencies for uWSGI
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpcre3 \
    libxml2 \
    && rm -rf /var/lib/apt/lists/*

# Add non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Create results directory for Locust output
RUN mkdir -p /app/results && chown -R appuser:appuser /app

# Environment defaults
ENV DJANGO_SETTINGS_MODULE=myapp.settings \
    UWSGI_PROCESSES=5 \
    UWSGI_THREADS=1 \
    CLOUDWATCH_ENABLED=True \
    CW_NAMESPACE=UWSGIWorkers \
    CW_PUSH_INTERVAL=10 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health/')" || exit 1

# Run uWSGI
CMD ["uwsgi", "--ini", "uwsgi.ini"]
