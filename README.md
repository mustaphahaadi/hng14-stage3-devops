# HNG Anomaly Detection Engine

A real-time HTTP traffic anomaly detector for Nextcloud running on cloud.ng. Watches all incoming HTTP traffic, learns what normal looks like, and automatically responds when something deviates—whether from a single aggressive IP or a global traffic spike.

**Live during evaluation at: [Your server IP and dashboard URL - will be updated before submission]**

## Project Overview

This project implements a **DevSecOps-grade anomaly detection system** that:

✅ **Continuously monitors** Nginx access logs in real-time (JSON format)  
✅ **Learns baselines** from actual traffic—no hardcoded thresholds  
✅ **Detects anomalies** using z-score and rate multiplier checks  
✅ **Blocks IPs** automatically via iptables DROP rules  
✅ **Auto-unbans** on a configurable backoff schedule (10 min → 30 min → 2 hours → permanent)  
✅ **Alerts via Slack** with full context (rate, baseline, condition, ban duration)  
✅ **Live metrics dashboard** refreshing every 3 seconds  
✅ **Structured audit logs** for every ban, unban, and baseline recalc  

---

## Architecture

### Components

```
Nginx (reverse proxy, JSON logs)
    ↓
[Shared Volume: HNG-nginx-logs]
    ↓ (read-only)
Detector Daemon (Python)
    ├─ Monitor (tails logs, sliding window)
    ├─ Baseline Calculator (rolling 30-min window per hour)
    ├─ Anomaly Detector (z-score + rate multiplier)
    ├─ IP Blocker (iptables DROP rules)
    ├─ Auto-Unbanner (backoff schedule)
    ├─ Slack Notifier (alerts)
    └─ Dashboard Web UI (live metrics at :8000)
```

### Docker Stack

- **nginx:alpine** — Reverse proxy with JSON request logging
- **kefaslungu/hng-nextcloud** — Nextcloud (not modified)
- **mariadb:latest** — Database for Nextcloud
- **detector (custom)** — Python anomaly detection daemon

---

## Quick Start

### Prerequisites

- Linux VPS with 2+ vCPU, 2+ GB RAM (tested on Ubuntu 20.04+)
- Docker and Docker Compose installed
- Git
- Slack workspace with incoming webhook (for alerts)

### 1. Clone Repository

```bash
git clone https://github.com/mustaphahaadi/hng-anomaly-detector.git
cd hng-anomaly-detector
```

### 2. Set Up Slack Webhook

1. Create a Slack app or use an existing workspace
2. Create an incoming webhook: https://api.slack.com/messaging/webhooks
3. Copy the webhook URL

### 3. Create Environment File

```bash
cat > .env <<EOF
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
COMPOSE_PROJECT_NAME=hng-detector
EOF
```

### 4. Build and Start the Stack

```bash
# Build detector image
docker-compose build detector

# Start all services
docker-compose up -d

# Verify services are running
docker-compose ps
```

### 5. Access Services

- **Nextcloud**: `http://<your-server-ip>/`
- **Metrics Dashboard**: `http://<your-server-ip>:8000/`
- **Nginx logs** (on host): `docker exec hng-nginx tail -f /var/log/nginx/hng-access.log`

### 6. View Audit Logs

```bash
docker exec hng-detector tail -f /var/log/hng-detector/audit.log
```

---

## How It Works

### Sliding Window (Per-IP + Global)

**Structure**: `deque of (timestamp, count)` for each second in the last 60 seconds.

**Eviction**: Old entries are removed automatically when they exceed 60 seconds. Each data point represents the total requests for that IP/global in a 1-second bucket.

```python
# From monitor.py
self.per_ip_window = defaultdict(deque)  # {ip: deque([(ts, count), ...])}
self.global_window = deque()              # [(ts, count), ...]

# Every second, aggregate and flush
self.global_window.append((current_second, self.current_second_global_count))

# Cleanup old entries outside window
cutoff = current_second - self.window_seconds
while self.global_window and self.global_window[0][0] < cutoff:
    self.global_window.popleft()
```

**Rate Calculation**: Average of counts across all windows.

```python
def get_global_rate(self):
    if not self.global_window:
        return 0.0
    return sum(count for _, count in self.global_window) / len(self.global_window)
```

### Baseline Calculator (Rolling 30-Minute Window)

**Structure**: Per-hour deques of per-second counts—up to 1 hour (3600 seconds) per slot.

```python
self.global_hour_data = defaultdict(lambda: deque(maxlen=3600))  # {hour: deque([...counts...])}
```

**Recalculation**: Every 60 seconds, compute mean and stddev from the rolling 30-minute window, preferring the current hour if it has data.

**Floor Values**:
- Effective mean: minimum 1.0 req/s (prevents false negatives on low traffic)
- Effective stddev: minimum 0.1 (ensures detection isn't impossible)

```python
def _calculate_baseline_for_window(self, hour_data_dict, current_hour):
    # Use current hour if available, else previous hour
    if current_hour in hour_data_dict and len(hour_data_dict[current_hour]) > 0:
        data = list(hour_data_dict[current_hour])
    elif (current_hour - 1) in hour_data_dict:
        data = list(hour_data_dict[current_hour - 1])
    else:
        return 1.0, 0.1  # Default safe baseline
    
    calc_mean = mean(data)
    calc_stddev = stdev(data)
    
    return max(calc_mean, 1.0), max(calc_stddev, 0.1)
```

### Anomaly Detection

**Per-IP Detection** (triggers blocking):

1. **Z-Score Check**: `z = (rate - mean) / stddev > 3.0`
2. **Rate Multiplier**: `rate / mean > 5.0`
3. **Error Rate Spike**: If `current_error_rate / baseline_error_rate > 3.0`, tighten thresholds for that IP for 5 minutes

Whichever fires first triggers a ban.

**Global Detection** (alerts only, no blocking):

- **Rate Multiplier**: `global_rate / baseline_mean > 5.0`

### Blocking (iptables)

```python
def block_ip(self, ip, reason):
    cmd = ['sudo', 'iptables', '-I', 'INPUT', '-s', ip, '-j', 'DROP']
    subprocess.run(cmd, ...)
    self.blocked_ips[ip] = {'blocked_at': time.time(), 'reason': reason}
```

### Auto-Unban Backoff Schedule

1. **First ban**: Unban after 10 minutes
2. **Re-offend**: Unban after 30 minutes
3. **Re-offend again**: Unban after 2 hours
4. **Still offending**: Permanent ban

Each unban sends a Slack notification with attempt count.

---

## Configuration

Edit [`config.yaml`](./config.yaml):

```yaml
detection:
  z_score_threshold: 3.0              # Standard deviations (higher = less sensitive)
  rate_multiplier: 5.0                # Multiplier of baseline mean
  error_rate_multiplier: 3.0          # 3x baseline error rate triggers tightening
  global_anomaly_multiplier: 5.0      # Global rate multiplier threshold

windows:
  short_window: 60                    # 60-second sliding window for rate
  baseline_window: 1800               # 30-minute rolling window
  baseline_recalc_interval: 60        # Recalculate every 60 seconds

unbanner:
  schedule: [600, 1800, 7200]         # Minutes: 10, 30, 120
  permanent_after: 43200              # 12 hours -> permanent ban

slack:
  webhook_url: "${SLACK_WEBHOOK_URL}" # Set via env var
  timeout: 10
```

---

## Slack Alerts

### Ban Alert (Per-IP)
```
🚫 *IP BANNED*
IP: `192.0.2.1`
Condition: z_score (z=4.5)
Current Rate: 150.32 req/s
Baseline: 10.50 req/s
Ban Duration: 10 minutes
Timestamp: 2024-01-15 14:23:45
```

### Unban Alert
```
✅ *IP UNBANNED*
IP: `192.0.2.1`
Reason: Backoff schedule - attempt 1/3
Timestamp: 2024-01-15 14:33:46
```

### Global Anomaly Alert
```
⚠️ *GLOBAL ANOMALY DETECTED*
Condition: global_rate_multiplier (mult=6.2)
Current Rate: 1050.50 req/s
Baseline: 165.00 req/s
Timestamp: 2024-01-15 14:25:10
```

---

## Audit Log Format

```
[2024-01-15 14:23:45] BAN | IP:192.0.2.1 | z_score (z=4.5) | rate:150.32 | baseline:10.50 | duration:10m
[2024-01-15 14:33:46] UNBAN | IP:192.0.2.1 | Backoff schedule - attempt 1/3
[2024-01-15 14:35:00] BASELINE_RECALC | baseline:10.75
[2024-01-15 14:35:00] GLOBAL_ANOMALY | global_rate_multiplier (mult=6.2) | rate:1050.50 | baseline:165.00
```

---

## Monitoring Blocked IPs

### Check Active iptables Rules

```bash
docker exec hng-detector sudo iptables -L -n | grep DROP
```

### Manually Unblock (if needed)

```bash
docker exec hng-detector sudo iptables -D INPUT -s 192.0.2.1 -j DROP
```

---

## Testing

### Simulate Traffic Spike

```bash
# Spike from a single IP (replace 192.0.2.100 with test IP)
docker exec hng-nginx bash -c \
  'for i in {1..1000}; do curl -s http://localhost/ > /dev/null; done &'
```

### Monitor in Real-Time

Terminal 1: Watch logs
```bash
docker exec hng-detector tail -f /var/log/hng-detector/detector.log
```

Terminal 2: Watch Nginx requests
```bash
docker exec hng-nginx tail -f /var/log/nginx/hng-access.log | jq '.'
```

Terminal 3: Check dashboard
```bash
open http://localhost:8000/
```

---

## Production Deployment

### Security Considerations

1. **HTTPS**: Uncomment redirect in nginx.conf, add SSL certs to `./certs/`
2. **Credentials**: Use strong Nextcloud passwords, store in secure secret manager
3. **Network**: Run on private VPC, use VPN for admin access
4. **Firewall**: Restrict Slack webhook to internal networks
5. **Logs**: Ship audit logs to centralized logging system (e.g., Datadog, ELK)

### Performance Tuning

- Increase `worker_processes` in nginx.conf for high traffic
- Tune `proxy_buffer_size` for file uploads
- Monitor memory usage of detector (run `docker stats`)

### High Availability

- Use container orchestration (Kubernetes) for automated failover
- Share nginx logs via distributed volume (NFS, S3)
- Use managed database (RDS) instead of local MariaDB

---

## Project Structure

```
.
├── detector/
│   ├── main.py              # Entry point, orchestrates all modules
│   ├── monitor.py           # Tails logs, sliding window aggregation
│   ├── baseline.py          # Rolling baseline calculator
│   ├── detector.py          # Anomaly detection logic
│   ├── blocker.py           # iptables blocking
│   ├── unbanner.py          # Auto-unban backoff schedule
│   ├── notifier.py          # Slack alerts
│   ├── dashboard.py         # Flask web UI
│   ├── config.yaml          # Configuration (thresholds, timeouts, etc.)
│   ├── requirements.txt     # Python dependencies
│   └── Dockerfile           # Detector image definition
├── nginx/
│   └── nginx.conf           # Nginx config with JSON logging
├── docker-compose.yml       # Services orchestration
├── README.md                # This file
└── docs/
    └── architecture.png     # Architecture diagram
```

---

## Language Choice: Python

**Why Python?**
- Rapid development of complex logic (baseline calculations, deque management)
- Rich ecosystem (Flask, psutil, requests) for web UI and system monitoring
- Clear, readable code for security auditing
- Excellent JSON parsing and log processing capabilities

**Why NOT Go?**
- Go would require more boilerplate for async I/O and concurrency primitives
- For a learning project, Python's simplicity and debuggability outweigh performance gains

---

## Blog Post

Read the beginner-friendly explanation here:
[Published on Hashnode](https://yourbloglink.com) *(link will be provided before final submission)*

The blog post covers:
- What is anomaly detection and why it matters
- How sliding windows aggregate traffic
- How baselines learn from real data
- How z-scores detect deviations
- How iptables blocks malicious IPs

---

## Screenshots (Required for Submission)

1. **Tool-running.png** — Detector daemon running, processing log lines ([screenshots/tool-running.png](./screenshots/))
2. **Ban-slack.png** — Slack ban notification ([screenshots/ban-slack.png](./screenshots/))
3. **Unban-slack.png** — Slack unban notification ([screenshots/unban-slack.png](./screenshots/))
4. **Global-alert-slack.png** — Slack global anomaly notification ([screenshots/global-alert-slack.png](./screenshots/))
5. **Iptables-banned.png** — `sudo iptables -L -n` showing a blocked IP ([screenshots/iptables-banned.png](./screenshots/))
6. **Audit-log.png** — Structured audit log with ban, unban, baseline events ([screenshots/audit-log.png](./screenshots/))
7. **Baseline-graph.png** — Baseline over time showing hourly differences ([screenshots/baseline-graph.png](./screenshots/))

---

## Known Limitations & Future Improvements

- **Permanent bans require manual review**: After 12 hours, bans are permanent. Consider a review queue.
- **No IP reputation service** for known attack sources.
- **Single-host deployment**: Distributed setup would require shared log backend.
- **No geo-blocking**: Could enhance with IP geolocation.

---

## Support & Troubleshooting

### Detector not reading logs
```bash
docker exec hng-detector cat /var/log/nginx/hng-access.log | wc -l
```

### Slack webhook not working
```bash
# Test webhook manually
curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"Test"}' \
  https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

### Check detector logs
```bash
docker logs -f hng-detector
```

---

## License

This project is created for HNG Internship Stage 3 DevOps Challenge.

---

---

**Server Status**: 🟢 Live  
**Dashboard**: [IP: To be added later]:8000  
**Metrics Updated**: Every 3 seconds  
**Audit Log**: `/var/log/hng-detector/audit.log`
