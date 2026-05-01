#!/bin/bash
# HNG Anomaly Detection Engine - Quick Start Script
# Usage: ./deploy.sh [SLACK_WEBHOOK_URL]

set -e

SLACK_WEBHOOK_URL="${1:-${SLACK_WEBHOOK_URL}}"

if [ -z "$SLACK_WEBHOOK_URL" ]; then
    echo "❌ Error: Slack webhook URL required"
    echo "Usage: ./deploy.sh 'https://hooks.slack.com/services/YOUR/WEBHOOK/URL'"
    echo "Or set SLACK_WEBHOOK_URL environment variable"
    exit 1
fi

echo "🚀 Starting HNG Anomaly Detection Engine deployment..."

# Create .env file
cat > .env <<EOF
SLACK_WEBHOOK_URL=$SLACK_WEBHOOK_URL
COMPOSE_PROJECT_NAME=hng-detector
EOF

echo "✓ Environment configured"

# Create directories
mkdir -p screenshots
mkdir -p certs

# Copy config to detector
cp config.yaml detector/config.yaml

# Build images
echo "📦 Building Docker images..."
docker-compose build

# Start services
echo "🟢 Starting services..."
docker-compose up -d

# Wait for services to start
echo "⏳ Waiting for services to be ready..."
sleep 10

# Check status
echo ""
echo "📊 Service Status:"
docker-compose ps

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📍 Access Points:"
echo "   • Nextcloud: http://localhost/"
echo "   • Dashboard: http://localhost:8000/"
echo ""
echo "📋 Monitor logs:"
echo "   docker-compose logs -f detector"
echo ""
echo "🔍 View audit log:"
echo "   docker exec hng-detector tail -f /var/log/hng-detector/audit.log"
echo ""
echo "🛑 Stop services:"
echo "   docker-compose down"
