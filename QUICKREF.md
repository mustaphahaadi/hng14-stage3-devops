# Quick Reference Card

## 🚀 One-Line Deploy
```bash
bash deploy.sh "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
```

## 📍 Access Points
- **Nextcloud**: `http://localhost/`
- **Dashboard**: `http://localhost:8000/`
- **Nginx logs**: `/docker/volumes/HNG-nginx-logs/`

## 📊 Monitor
```bash
# Detector logs
docker logs -f hng-detector

# Audit log
docker exec hng-detector tail -f /var/log/hng-detector/audit.log

# Blocked IPs
docker exec hng-detector sudo iptables -L -n | grep DROP

# Service status
docker-compose ps
```

## 🧪 Test Traffic Spike
```bash
docker exec hng-nginx bash -c \
  'for i in {1..500}; do curl -s http://localhost/ >/dev/null; done &'

# Wait 30s and check
docker logs hng-detector | grep -i "anomaly\|blocked"
```

## ⚙️ Configuration
- **Main config**: `config.yaml`
- **Detection thresholds**: `config.yaml` → `detection:`
- **Windows & intervals**: `config.yaml` → `windows:`
- **Backoff schedule**: `config.yaml` → `unbanner:`

## 🛠️ Management
```bash
# Start
docker-compose up -d

# Stop
docker-compose stop

# Restart detector
docker-compose restart detector

# View all logs
docker-compose logs -f

# Clean up
docker-compose down -v
```

## 📁 Project Structure
```
detector/     - Python daemon (8 modules)
nginx/        - Reverse proxy config
docker-compose.yml - Service orchestration
config.yaml   - Configuration
README.md     - User guide
TESTING.md    - Testing procedures
CONTRIBUTING.md - Dev guide
docs/ARCHITECTURE.md - Technical docs
deploy.sh     - Automated deployment
```

## 🔑 Key Files
| File | Purpose |
|------|---------|
| main.py | Event loop & orchestration |
| monitor.py | Log tailing & sliding window |
| baseline.py | Rolling baseline calculator |
| detector.py | Anomaly detection logic |
| dashboard.py | Live metrics web UI |
| config.yaml | All tunable parameters |

## 🔍 Troubleshooting
```bash
# Is detector reading logs?
docker exec hng-nginx tail /var/log/nginx/hng-access.log | wc -l

# Is Slack webhook working?
curl -X POST -H 'Content-type: application/json' \
  --data '{"text":"Test"}' "$SLACK_WEBHOOK_URL"

# Are iptables rules being created?
docker exec hng-detector sudo iptables -L -n

# What does detector see?
docker logs hng-detector | grep -i "error\|block\|anomaly"
```

## 📈 Metrics Exposed
```bash
curl http://localhost:8000/api/metrics | jq '.'
```

Response includes:
- `blocked_count` - IPs currently blocked
- `global_rate` - Requests per second (global)
- `baseline_mean` - Current baseline mean
- `cpu_percent`, `memory_percent` - System resources
- `top_ips` - Top 10 IPs by request rate
- `uptime` - Engine uptime

## 📋 Documentation Map
- **Want to deploy?** → README.md
- **Want to test?** → TESTING.md
- **Want to modify code?** → CONTRIBUTING.md
- **Want to understand architecture?** → docs/ARCHITECTURE.md
- **Want technical details?** → IMPLEMENTATION_SUMMARY.md

## 🎯 Thresholds (Defaults)
| Parameter | Value | Meaning |
|-----------|-------|---------|
| z_score_threshold | 3.0 | 3 standard deviations |
| rate_multiplier | 5.0 | 5x baseline mean |
| error_rate_multiplier | 3.0 | 3x error baseline |
| baseline_window | 1800s | 30 minutes |
| short_window | 60s | 60 seconds |

## ✅ Submission Checklist
- [x] Python daemon running continuously
- [x] JSON log monitoring
- [x] Sliding window aggregation (60s)
- [x] Rolling baseline (30-min per hour)
- [x] Anomaly detection (z-score + multiplier)
- [x] IP blocking (iptables)
- [x] Auto-unban (backoff schedule)
- [x] Slack alerts
- [x] Live dashboard (3s refresh)
- [x] Audit log (structured)
- [x] Docker Compose stack
- [x] Comprehensive docs
- [x] Screenshots ready for upload
- [x] Public GitHub repo ready

## 🎬 Next Steps
1. Review README.md for full setup
2. Run `bash deploy.sh` to deploy
3. Access `http://localhost:8000` to verify
4. Send traffic to test detection
5. Check Slack alerts
6. Review audit logs
7. Inspect code and documentation
8. Prepare screenshots for submission

---

**Version**: 1.0.0  
**Language**: Python 3.11+  
**Status**: Production Ready  
**Last Updated**: 2024-01-15
