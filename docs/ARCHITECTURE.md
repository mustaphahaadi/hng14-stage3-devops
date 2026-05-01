---
title: HNG Anomaly Detection Engine - Architecture & Design
author: HNG Internship DevOps Track
date: 2024-01-15
---

# System Architecture

## High-Level Overview

```
┌──────────────────────────────────────────────────────────────┐
│                     Public Internet Traffic                  │
└────────────────────────┬─────────────────────────────────────┘
                         │
        ┌────────────────▼────────────────┐
        │   Nginx Reverse Proxy (80/443)  │
        │  Port: 80, Host: 0.0.0.0        │
        |  - X-Forwarded-For trusted      │
        │  - JSON access logs enabled     │
        └────────────────┬────────────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        │        ┌───────▼────────┐       │
        │        │   Nextcloud    │       │
        │        │   (Container)  │       │
        │        └────────────────┘       │
        │                                 │
        │        ┌───────────────┐        │
        │        │   MariaDB     │        │
        │        │   (Database)  │        │
        │        └───────────────┘        │
        │                                 │
        │  Docker Network: hng-network    │
        └─────────────────┬───────────────┘
                         │
        ┌────────────────▼────────────────┐
        │   HNG-nginx-logs Volume         │
        │   (shared by nginx & detector)  │
        └────────────────┬────────────────┘
                         │
                   (read-only)
                         │
        ┌────────────────▼────────────────────────┐
        │  Anomaly Detection Engine (Container)   │
        │────────────────────────────────────────│
        │                                         │
        │  ┌─────────────────────────────────┐   │
        │  │ Monitor Module                  │   │
        │  │ - Tails nginx logs              │   │
        │  │ - Parses JSON entries           │   │
        │  │ - Sliding 60s window (per-IP)   │   │
        │  │ - Sliding 60s window (global)   │   │
        │  └─────────────────────────────────┘   │
        │                    ▼                    │
        │  ┌─────────────────────────────────┐   │
        │  │ Baseline Calculator             │   │
        │  │ - Per-hour rolling window       │   │
        │  │ - 30-minute data retention      │   │
        │  │ - Recalc every 60s              │   │
        │  │ - Mean + StdDev with floors     │   │
        │  └─────────────────────────────────┘   │
        │                    ▼                    │
        │  ┌─────────────────────────────────┐   │
        │  │ Anomaly Detector                │   │
        │  │ - Z-score check (>3.0)          │   │
        │  │ - Rate multiplier (>5x)         │   │
        │  │ - Error spike detection (3x)    │   │
        │  │ - Threshold tightening logic    │   │
        │  └─────────────────────────────────┘   │
        │                    ▼                    │
        │  ┌──────────────────┬──────────────┐   │
        │  │                  │              │   │
        │  │ Per-IP Anomaly   │  Global      │   │
        │  │                  │  Anomaly     │   │
        │  └────────┬─────────┴──────┬───────┘   │
        │           │                │           │
        │           ▼                ▼           │
        │  ┌──────────────┐  ┌──────────────┐   │
        │  │ IP Blocker   │  │ Notifier     │   │
        │  │ (iptables)   │  │ (Slack)      │   │
        │  └──────┬───────┘  └──────┬───────┘   │
        │         │                 │           │
        │         ▼                 ▼           │
        │  ┌──────────────┐  ┌──────────────┐   │
        │  │ Unbanner     │  │ Audit Logger │   │
        │  │ (backoff)    │  │              │   │
        │  └──────────────┘  └──────────────┘   │
        │                                         │
        │  ┌─────────────────────────────────┐   │
        │  │ Dashboard Web UI (Flask)        │   │
        │  │ Port: 8000                      │   │
        │  │ Refresh: 3 seconds              │   │
        │  ?─────────────────────────────────┘   │
        │                                         │
        └─────────────────────────────────────────┘
```

---

## Data Flow: Detection → Block → Alert

### 1. Log Ingestion (Every 100ms)

```
Nginx Log Line (JSON)
    ↓
LogMonitor.read_log_lines()
    ├─ Parse JSON (source_ip, status, method, etc.)
    ├─ Aggregate per IP, per second
    ├─ Track 4xx/5xx errors
    └─ Maintain sliding 60-second window
```

**Example Nginx Log Entry:**
```json
{
  "timestamp": "2024-01-15T14:23:45+00:00",
  "source_ip": "192.0.2.1",
  "method": "GET",
  "path": "/remote.php/dav/files/user/large_file.zip",
  "status": 200,
  "response_size": 1048576,
  "request_time": 2.5
}
```

### 2. Per-Second Aggregation (Every 1 second)

```
Current Second's Data:
  ├─ IP 192.0.2.1: 120 requests
  ├─ IP 203.0.113.5: 15 requests
  └─ Global: 250 requests

Add to Baseline Calculator:
  └─ baseline_calc.add_request_count(
       global_count=250,
       per_ip_counts={'192.0.2.1': 120, '203.0.113.5': 15}
     )
```

### 3. Baseline Recalculation (Every 60 seconds)

```
Rolling 30-min window (current hour + previous hour):
  ├─ Per-IP 192.0.2.1: [120, 125, 115, ..., 110] per second
  │   └─ Mean: 118.2 req/s, StdDev: 4.3
  │   └─ Effective: max(118.2, 1.0), max(4.3, 0.1)
  │
  └─ Global: [250, 255, 245, ..., 240] per second
      └─ Mean: 248.5 req/s, StdDev: 6.2
      └─ Effective: max(248.5, 1.0), max(6.2, 0.1)
```

### 4. Anomaly Check (Every second)

```
For each active IP:
  ├─ Current rate: 850 req/s (from sliding window)
  ├─ Baseline mean: 118.2 req/s
  ├─ Baseline stddev: 4.3
  ├─ Z-score: (850 - 118.2) / 4.3 = 170.0
  │
  ├─ Check 1: Z-score > 3.0? YES (170.0 >> 3.0) → 🚩 ANOMALY
  │
  └─ Also check: Rate multiplier = 850 / 118.2 = 7.2x (> 5x) → ALSO ANOMALY

Result: IP 192.0.2.1 is ANOMALOUS
```

### 5. Blocking (Immediate on Detection)

```
if is_anomalous:
    ├─ Add iptables rule: sudo iptables -I INPUT -s 192.0.2.1 -j DROP
    ├─ Add to AutoUnbanner schedule
    ├─ Send Slack alert (5-second SLA)
    └─ Write audit log

Slack Message:
  🚫 *IP BANNED*
  IP: `192.0.2.1`
  Condition: z_score (z=170.0)
  Current Rate: 850.00 req/s
  Baseline: 118.20 req/s
  Ban Duration: 10 minutes
```

### 6. Auto-Unban (Backoff Schedule)

```
IP 192.0.2.1 banned at T=0
    │
    ├─ T+10min → Check if still anomalous
    │           ├─ Still seeing 850 req/s? → REBAN (attempt 2, unban at +30min)
    │           └─ Dropped to 120 req/s? → UNBAN (send notification)
    │
    ├─ T+30min → Check again
    │
    ├─ T+2hrs  → Check again
    │
    └─ T+12hrs → PERMANENT BAN (if never gets traffic below threshold)
```

---

## Module Details

### LogMonitor (monitor.py)

**Purpose**: Tail Nginx access log, parse JSON, aggregate per second.

**Key Data Structures**:
```python
per_ip_window = defaultdict(deque)      # {ip: [(ts, count), ...]}
global_window = deque()                 # [(ts, count), ...]
per_ip_errors = defaultdict(deque)      # {ip: [(ts, count), ...]}
global_errors = deque()                 # [(ts, count), ...]
```

**Lifecycle**:
1. Open log file, seek to end (skip history)
2. Read new lines continuously
3. Parse JSON, extract metrics
4. Aggregate per second
5. Clean up entries > 60 seconds old

**Rate Calculation**:
```python
rate = sum(all_counts) / len(all_counts)
# Example: [100, 105, 98, 102, 101] → 101.2 req/s
```

### BaselineCalculator (baseline.py)

**Purpose**: Compute rolling 30-minute baseline with hourly slots.

**Key Data Structures**:
```python
global_hour_data = {
    hour_N: deque([120, 125, 115, ...]),      # Per-second counts
    hour_N-1: deque([118, 122, 119, ...])
}
per_ip_hour_data = {
    '192.0.2.1': {
        hour_N: deque([...]),
        hour_N-1: deque([...])
    }
}
```

**Logic**:
```python
def recalculate_baselines():
    # Prefer current hour; fall back to previous
    if current_hour_data:
        use_data = current_hour_data
    else:
        use_data = previous_hour_data
    
    mean = statistics.mean(use_data)
    stddev = statistics.stdev(use_data) if len(use_data) > 1 else 0
    
    # Apply floors
    effective_mean = max(mean, 1.0)
    effective_stddev = max(stddev, 0.1)
```

### AnomalyDetector (detector.py)

**Purpose**: Apply z-score and rate multiplier checks.

**Decision Tree** (Per-IP):
```
Is error rate 3x baseline?
    ├─ YES → Tighten thresholds for 5 minutes
    │        (z_threshold *= 0.6, rate_mult *= 0.5)
    └─ NO

Check z-score:
    ├─ z > 3.0? → BLOCK (condition: z_score)
    └─ NO

Check rate multiplier:
    ├─ rate/baseline > 5.0? → BLOCK (condition: rate_multiplier)
    └─ NO → CLEAN
```

**Global (No block, alerts only)**:
```
Check rate multiplier:
    ├─ rate/baseline > 5.0? → ALERT (no block)
    └─ NO
```

### IPBlocker (blocker.py)

**Purpose**: Manage iptables DROP rules.

```python
def block_ip(ip, reason):
    cmd = ['sudo', 'iptables', '-I', 'INPUT', '-s', ip, '-j', 'DROP']
    # Inserts rule at top of INPUT chain

def unblock_ip(ip):
    cmd = ['sudo', 'iptables', '-D', 'INPUT', '-s', ip, '-j', 'DROP']
    # Deletes rule from INPUT chain
```

**Tracking**:
```python
blocked_ips = {
    '192.0.2.1': {
        'blocked_at': 1705334625,  # Unix timestamp
        'reason': 'z_score (z=170.0)'
    }
}
```

### AutoUnbanner (unbanner.py)

**Purpose**: Manage backoff unban schedule.

**Backoff Logic**:
```
Unban attempt 0: blocked_at + 10min
Unban attempt 1: blocked_at + 10min + 30min = 40min
Unban attempt 2: blocked_at + 10min + 30min + 2hrs = 2h40min
Unban attempt 3+: permanent (never unban)
```

**Process**:
```python
def should_unban_now(ip):
    if still_anomalous(ip):
        return False
    
    time_elapsed = now - blocked_at
    next_unban_time = blocked_at + sum(backoff[:attempts])
    
    return time_elapsed >= next_unban_time
```

### Notifier (notifier.py)

**Purpose**: Send Slack alerts with context.

**Alert Types**:

1. **Ban** (per-IP):
   ```json
   {
     "text": "🚫 IP BANNED",
     "IP": "192.0.2.1",
     "condition": "z_score (z=170.0)",
     "rate": "850.00 req/s",
     "baseline": "118.20 req/s",
     "duration": "10 minutes"
   }
   ```

2. **Unban**:
   ```json
   {
     "text": "✅ IP UNBANNED",
     "IP": "192.0.2.1",
     "reason": "Backoff schedule - attempt 1/3"
   }
   ```

3. **Global Anomaly** (alert only):
   ```json
   {
     "text": "⚠️ GLOBAL ANOMALY",
     "condition": "global_rate_multiplier (mult=6.2)",
     "rate": "1050.50 req/s",
     "baseline": "165.00 req/s"
   }
   ```

**Anti-Spam**:
```python
# Minimum 10 seconds between identical alerts
alert_cache = {'ban:192.0.2.1': last_alert_time}
```

### Dashboard (dashboard.py)

**Purpose**: Live metrics web UI (Flask).

**Endpoints**:
- `GET /` — HTML dashboard
- `GET /api/metrics` — JSON metrics
- `GET /api/status` — Service health

**Metrics Exposed**:
```json
{
  "blocked_count": 3,
  "global_rate": 245.50,
  "baseline_mean": 165.00,
  "baseline_stddev": 12.5,
  "cpu_percent": 5.2,
  "memory_percent": 18.7,
  "uptime": "2h 34m 12s",
  "blocked_ips": ["192.0.2.1", "203.0.113.5"],
  "top_ips": [
    {"ip": "10.0.0.50", "rate": 120.5},
    {"ip": "10.0.0.51", "rate": 95.3}
  ]
}
```

**UI Features**:
- Auto-refresh every 3 seconds
- Real-time metrics grid
- Blocked IPs list
- Top 10 IPs by rate
- System resource usage
- Uptime counter

---

## Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `z_score_threshold` | 3.0 | Z-score trigger point |
| `rate_multiplier` | 5.0 | Rate multiplier trigger |
| `error_rate_multiplier` | 3.0 | Error spike sensitivity |
| `short_window` | 60s | Rate window (sliding) |
| `baseline_window` | 1800s | Baseline window (30 min) |
| `baseline_recalc_interval` | 60s | How often to recalc |
| `backoff_schedule` | [10m, 30m, 2h] | Unban delays |
| `permanent_after` | 12h | Permanent ban threshold |

---

## State Transitions

### Per-IP State Machine

```
   [CLEAN]
      ↓ (anomaly detected)
   [BLOCKED]
      ↓ (backoff timer + traffic OK)
   [REVIEW] (attempt 1 of 3)
      ├─ Still anomalous → [BLOCKED] (attempt 2)
      └─ Clean → [CLEAN]
```

### Global State

- No state machine for global (just alerts)
- Multiple global anomalies don't stack
- Minimum 30 seconds between identical alerts

---

## Performance Characteristics

| Component | Time Complexity | Space Complexity | Notes |
|-----------|-----------------|------------------|-------|
| Log parsing | O(1) per line | O(IPs) for tracking | No full scan |
| Sliding window | O(1) amortized | O(60 * IPs) | Deque eviction |
| Baseline calc | O(data points) | O(3600 * IPs) | Once per 60s |
| Detection | O(active IPs) | O(tightened IPs) | Per second |
| iptables rule | O(1) | N/A | System call |
| Dashboard | O(IPs) | O(metrics) | Every 3s |

**Typical Memory**: ~50MB for 10k active IPs over 1 hour

---

## Error Handling

| Scenario | Handling | Alert |
|----------|----------|-------|
| Log file missing | Retry on next poll | Logged |
| Slack webhook down | Retry, log error | Error log |
| iptables rule fail | Log error, skip block | Error log |
| Baseline insufficient data | Use floor values | Debug log |
| JSON parse error | Skip entry, count total | Debug log |

---

## Testing Checklist

- [ ] Start detector, verify log tail works
- [ ] Send normal traffic, confirm baseline calculates
- [ ] Send spike traffic, confirm detection
- [ ] Verify iptables rule created
- [ ] Verify Slack alert sent
- [ ] Check audit log entry
- [ ] Wait 10 minutes, verify auto-unban
- [ ] Verify Slack unban notification
- [ ] Check dashboard displays blocked IP
- [ ] Reblock same IP, verify backoff increases duration

---

## Future Enhancements

1. **Machine Learning**: Replace z-score with LSTM for pattern learning
2. **IP Reputation**: Query AbuseIPDB for known malicious IPs
3. **Geo-blocking**: Block countries not in whitelist
4. **Rate Limiting**: Soft limit before hard block
5. **Distributed Logging**: Send logs to centralized system
6. **Web UI Alerts**: In-dashboard notifications
7. **Manual Review Queue**: Queue for security team approval before permanent bans

---

## References

- Nginx JSON logging: https://nginx.org/en/docs/http/ngx_http_log_module.html
- iptables filter rule: https://linux.die.net/man/8/iptables
- Z-score: https://en.wikipedia.org/wiki/Standard_score
- Slack Webhooks: https://api.slack.com/messaging/webhooks
- Flask: https://flask.palletsprojects.com/
