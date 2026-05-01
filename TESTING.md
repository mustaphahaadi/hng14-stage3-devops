# Testing & Troubleshooting Guide

## Quick Deployment

```bash
# Set webhook and deploy
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
bash deploy.sh

# Or with inline parameter
bash deploy.sh "https://hooks.slack.com/services/..."
```

---

## Pre-Flight Checks

### 1. Verify Docker & Compose

```bash
docker --version        # Docker installed
docker-compose --version  # Docker Compose installed
docker ps              # Docker daemon running
```

### 2. Verify Host Requirements

```bash
# Check CPU count (need 2+)
nproc

# Check RAM (need 2GB+)
free -h

# Check disk space (need 5GB+ for volumes)
df -h /

# Check sudoers for iptables (needed for blocking)
sudo iptables -L -n | head -5
```

### 3. Verify Slack Webhook

```bash
# Test webhook manually
WEBHOOK="https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"Test from HNG Detector"}' \
  "$WEBHOOK"

# Check response (should be "1")
```

---

## Deployment Steps

### Step 1: Clone and Setup

```bash
cd /path/to/project
mkdir -p screenshots
mkdir -p certs

# Create .env
cat > .env <<EOF
SLACK_WEBHOOK_URL=YOUR_WEBHOOK_HERE
COMPOSE_PROJECT_NAME=hng-detector
EOF
```

### Step 2: Build Detector Image

```bash
docker-compose build detector

# Verify build succeeded
docker images | grep hng-detector
```

### Step 3: Start Stack

```bash
docker-compose up -d

# Check all services running
docker-compose ps

# Expected:
# hng-nginx       Port 80
# hng-nextcloud   Running
# hng-mariadb     Running
# hng-detector    Port 8000
```

### Step 4: Verify Connectivity

```bash
# Check Nextcloud is accessible
curl -s http://localhost/ | grep -q "Nextcloud" && echo "✓ Nextcloud running"

# Check dashboard is accessible
curl -s http://localhost:8000/ | grep -q "Anomaly Detection" && echo "✓ Dashboard running"

# Check nginx logs exist
docker exec hng-nginx test -f /var/log/nginx/hng-access.log && echo "✓ Nginx logs ready"
```

### Step 5: Monitor Startup

```bash
# Watch detector initialization (should see "BaselineCalculator initialized" etc)
docker logs -f hng-detector | head -20
```

---

## Testing Scenarios

### Scenario 1: Normal Traffic

**Goal**: Verify baseline learns from clean traffic

```bash
# Generate normal requests
for i in {1..100}; do
  curl -s http://localhost/ >/dev/null &
done
wait

# Check detector logs
docker logs hng-detector | grep -i "baseline_recalc"

# Expected: "Baseline recalculated | mean=X | stddev=Y"
```

### Scenario 2: Single IP Spike

**Goal**: Verify per-IP detection and blocking

```bash
# Simulate attack from different IP (using curl in container)
docker exec hng-nginx bash -c \
  'for i in {1..500}; do curl -s http://localhost/ >/dev/null; done &'

# Wait 30 seconds for detection
sleep 30

# Check if IP was blocked
docker exec hng-detector sudo iptables -L -n | grep DROP

# Expected: Rule showing source IP dropped

# Check detector log
docker logs hng-detector | grep -i "ANOMALY\|BLOCKED"

# Check Slack alerts received
```

### Scenario 3: Global Spike

**Goal**: Verify global anomaly detection and alerting (no blocking)

```bash
# Generate massive global traffic
docker exec hng-nginx bash -c \
  'for i in {1..1000}; do curl -s http://localhost/ >/dev/null & done'

# Check for global anomaly alert in logs
docker logs hng-detector | grep -i "global_anomaly"

# Check Slack alert received
# Note: No blocking should occur for global anomalies
```

### Scenario 4: Auto-Unban

**Goal**: Verify backoff unban schedule

```bash
# After blocking an IP in Scenario 2, wait and check unban

# Get blocked IP
BLOCKED_IP=$(docker exec hng-detector sudo iptables -L -n | \
  grep DROP | awk '{print $4}' | grep -v "0.0.0.0")

echo "Blocked IP: $BLOCKED_IP"

# Wait for first unban window (10 minutes) - or test with reduced time
sleep 600

# Check if IP was unbanned
docker exec hng-detector sudo iptables -L -n | grep "$BLOCKED_IP" && \
  echo "Still blocked" || echo "✓ Unbanned"

# Check audit log
docker exec hng-detector grep "UNBAN" /var/log/hng-detector/audit.log | tail -5
```

---

## Log Inspection

### Nginx Access Log (JSON)

```bash
# View raw log
docker exec hng-nginx tail -f /var/log/nginx/hng-access.log

# Pretty-print JSON
docker exec hng-nginx tail -f /var/log/nginx/hng-access.log | jq '.'

# Count requests per IP
docker exec hng-nginx grep -o '"source_ip":"[^"]*"' \
  /var/log/nginx/hng-access.log | sort | uniq -c | sort -rn
```

### Detector Audit Log

```bash
# View audit log
docker exec hng-detector tail -f /var/log/hng-detector/audit.log

# Filter by action
docker exec hng-detector grep "^.*BAN\|^.*UNBAN" /var/log/hng-detector/audit.log
```

### Detector Application Log

```bash
# Stream logs
docker logs -f hng-detector

# Look for specific events
docker logs hng-detector | grep -i "anomaly\|blocked\|unban"

# Check baseline calculations
docker logs hng-detector | grep -i "baseline_recalc"

# Look for errors
docker logs hng-detector | grep -i "error"
```

---

## Dashboard Access

### Browser UI

Navigate to: `http://localhost:8000/`

**Visible on Dashboard:**
- Real-time request rate (req/s)
- Blocked IPs count
- Baseline mean and stddev
- CPU/Memory usage
- Top 10 IPs by rate
- System uptime
- Auto-refresh every 3 seconds

### API Endpoints

```bash
# Get metrics
curl http://localhost:8000/api/metrics | jq '.'

# Get status
curl http://localhost:8000/api/status | jq '.'
```

---

## Troubleshooting

### Issue: Detector not reading logs

**Check:**
```bash
# Is log file present?
docker exec hng-nginx test -f /var/log/nginx/hng-access.log && echo "Found"

# Are logs being written?
docker exec hng-nginx tail /var/log/nginx/hng-access.log | wc -l

# Is volume mounted correctly?
docker inspect hng-detector | grep -A 5 "Mounts"

# Check detector logs for errors
docker logs hng-detector | grep -i "error\|open\|file"
```

**Fix:**
```bash
# Restart nginx to ensure logs are being written
docker-compose restart nginx

# Wait and check again
sleep 5
docker exec hng-nginx tail /var/log/nginx/hng-access.log
```

### Issue: Slack webhook not working

**Check:**
```bash
# Is webhook URL set?
docker exec hng-detector grep "SLACK_WEBHOOK_URL" /proc/$(docker inspect -f '{{.State.Pid}}' hng-detector)/environ

# Test webhook manually
curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"Test"}' \
  "YOUR_WEBHOOK_URL"
```

**Fix:**
```bash
# Update .env with correct webhook
echo "SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/NEW/WEBHOOK" >> .env

# Restart detector
docker-compose restart detector
```

### Issue: iptables rule not created

**Check:**
```bash
# Does detector have sudo privileges?
docker exec hng-detector sudo -l

# Can detector run iptables?
docker exec hng-detector sudo iptables -L -n

# Check detector logs for iptables errors
docker logs hng-detector | grep -i "iptables\|block"
```

**Fix:**
```bash
# Detector needs privileged mode (should be in compose)
# Verify in docker-compose.yml: "privileged: true"

# Restart detector
docker-compose restart detector
```

### Issue: High memory usage

**Check:**
```bash
# Monitor memory
docker stats hng-detector

# Check what's consuming memory
docker exec hng-detector ps aux | head -5
```

**Fix:**
```bash
# Reduce window sizes in config.yaml
# Or increase container memory limits in docker-compose.yml

docker-compose restart detector
```

---

## Performance Monitoring

### Resource Usage

```bash
# Real-time stats
docker stats --no-stream

# Historical usage (requires logging driver)
docker exec hng-detector free -h
docker exec hng-detector top -bn1 | head -10
```

### Request Metrics

```bash
# Count requests over time
docker exec hng-nginx bash -c \
  'for i in {1..5}; do echo -n "$i: "; grep -c "status" /var/log/nginx/hng-access.log; sleep 2; done'

# Average response time
docker exec hng-nginx jq '.request_time' /var/log/nginx/hng-access.log | \
  awk '{sum+=$1; count++} END {print sum/count}'
```

---

## Cleanup & Shutdown

### Stop Stack (Keep Data)

```bash
docker-compose stop
```

### Stop and Remove Containers

```bash
docker-compose down
```

### Remove Everything (Reset)

```bash
docker-compose down -v  # Remove volumes too
```

### Logs & Artifacts

```bash
# Save audit log before cleanup
docker cp hng-detector:/var/log/hng-detector/audit.log ./audit.log.backup

# Save nginx logs
docker cp hng-nginx:/var/log/nginx/hng-access.log ./nginx-access.log.backup
```

---

## Security Audit Checklist

- [ ] Slack webhook URL stored in .env, not in code
- [ ] iptables rules are DROP only (not REJECT)
- [ ] Detector runs with minimal required privileges
- [ ] Nginx X-Forwarded-For is trusted only from Docker network
- [ ] Nextcloud admin password changed from default
- [ ] Database credentials changed from defaults
- [ ] HTTPS certificates configured (if prod)
- [ ] Audit logs retained for compliance
- [ ] No sensitive data in log output

---

## References

- Docker Compose docs: https://docs.docker.com/compose/
- iptables man page: https://linux.die.net/man/8/iptables
- Nginx logging: https://nginx.org/en/docs/http/ngx_http_log_module.html
- Flask documentation: https://flask.palletsprojects.com/
- Python logging: https://docs.python.org/3/library/logging.html
