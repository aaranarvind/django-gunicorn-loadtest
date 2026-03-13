#!/bin/bash
# EC2 User Data Script
# Bootstrap an EC2 instance to run the Django + uWSGI load testing stack.
#
# Usage: Paste this into EC2 Launch Template > User Data
# Or use: aws ec2 run-instances --user-data file://deploy/userdata.sh

set -euo pipefail

# ---- Variables (override via EC2 tags or parameter store) ----
UWSGI_PROCESSES="${UWSGI_PROCESSES:-5}"
UWSGI_THREADS="${UWSGI_THREADS:-1}"
APP_REPO="https://github.com/YOUR_USERNAME/django-uwsgi-loadtest.git"
AWS_REGION="${AWS_DEFAULT_REGION:-ap-south-1}"

# ---- System Updates ----
echo "📦 Installing system dependencies..."
yum update -y
yum install -y docker git

# ---- Start Docker ----
echo "🐳 Starting Docker..."
systemctl start docker
systemctl enable docker
usermod -aG docker ec2-user

# ---- Install Docker Compose ----
echo "🔧 Installing Docker Compose..."
COMPOSE_VERSION="v2.24.5"
curl -L "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" \
    -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# ---- Clone Application ----
echo "📥 Cloning application..."
cd /home/ec2-user
git clone "${APP_REPO}" app || {
    echo "⚠️  Git clone failed. Creating app directory with placeholder..."
    mkdir -p app
    echo "Place your application code here" > app/README.md
}
cd app

# ---- Get Instance ID for CloudWatch dimensions ----
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)

# ---- Create .env file ----
cat > .env << EOF
UWSGI_PROCESSES=${UWSGI_PROCESSES}
UWSGI_THREADS=${UWSGI_THREADS}
CLOUDWATCH_ENABLED=True
CW_NAMESPACE=UWSGIWorkers
CW_PUSH_INTERVAL=10
INSTANCE_ID=${INSTANCE_ID}
AWS_DEFAULT_REGION=${AWS_REGION}
EOF

# ---- Build and Start ----
echo "🚀 Building and starting application..."
docker-compose up -d --build web

echo "✅ Application started!"
echo "   - App URL: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4):8000"
echo "   - Processes: ${UWSGI_PROCESSES}"
echo "   - Threads: ${UWSGI_THREADS}"
echo "   - CloudWatch Namespace: UWSGIWorkers"
echo "   - Instance ID: ${INSTANCE_ID}"

# ---- Deploy CloudWatch Dashboard ----
echo "📊 Deploying CloudWatch dashboard..."
if [ -f deploy/cloudwatch_dashboard.json ]; then
    # Replace placeholder instance ID with actual
    sed -i "s/docker-local/${INSTANCE_ID}/g" deploy/cloudwatch_dashboard.json

    aws cloudwatch put-dashboard \
        --dashboard-name "UWSGIWorkerMonitoring" \
        --dashboard-body "file://deploy/cloudwatch_dashboard.json" \
        --region "${AWS_REGION}" || echo "⚠️  Dashboard deployment failed (check IAM permissions)"
fi

echo "🎉 Setup complete!"
