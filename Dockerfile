# ---- Build Stage ----
FROM python:3.11-slim AS builder

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Runtime Stage ----
FROM python:3.11-slim

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
    GUNICORN_WORKERS=5 \
    GUNICORN_THREADS=1 \
    GUNICORN_BIND=0.0.0.0:8000 \
    CLOUDWATCH_ENABLED=True \
    CW_NAMESPACE=GunicornWorkers \
    CW_PUSH_INTERVAL=10 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health/')" || exit 1

# Run Gunicorn
CMD ["gunicorn", "myapp.wsgi:application", "-c", "gunicorn.conf.py"]
