# Contributing & Development

## Development Environment Setup

### 1. Clone and Setup

```bash
git clone https://github.com/yourusername/hng-anomaly-detector.git
cd hng-anomaly-detector

# Create virtual environment (optional but recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Local Testing (Without Docker)

```bash
# Create dummy nginx log
mkdir -p logs
touch logs/hng-access.log

# Run detector directly
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
python detector/main.py
```

---

## Code Structure

### Module Responsibilities

| Module | Responsibility |
|--------|-----------------|
| `main.py` | Orchestration, main event loop |
| `monitor.py` | Log tailing, aggregation, sliding window |
| `baseline.py` | Rolling baseline calculation |
| `detector.py` | Anomaly detection logic (z-score, multipliers) |
| `blocker.py` | iptables integration |
| `unbanner.py` | Auto-unban backoff schedule |
| `notifier.py` | Slack alerts |
| `dashboard.py` | Flask web UI |

### Key Design Patterns

**1. Deque-based sliding window:**
```python
# Keep only last N seconds
self.global_window = deque(maxlen=60)  # Auto-evicts old entries
```

**2. Per-hour baseline storage:**
```python
# Hour-keyed dict with deques per slot
self.global_hour_data = defaultdict(lambda: deque(maxlen=3600))
```

**3. State tracking with dicts:**
```python
# Track state for each IP
self.blocked_ips = {ip: {'blocked_at': ts, 'reason': str}}
```

---

## Customization & Tuning

### Adjusting Thresholds

Edit `config.yaml`:

```yaml
detection:
  z_score_threshold: 3.0      # Lower = more sensitive to spikes
  rate_multiplier: 5.0        # Lower = more sensitive
  error_rate_multiplier: 3.0  # Lower = tighten thresholds sooner
```

### Adjusting Windows

```yaml
windows:
  short_window: 60            # Sliding window for rate (seconds)
  baseline_window: 1800       # Baseline calculation window (seconds)
  baseline_recalc_interval: 60  # How often to recalc (seconds)
```

### Adjusting Unban Schedule

```yaml
unbanner:
  schedule: [600, 1800, 7200]  # 10 min, 30 min, 2 hours
  permanent_after: 43200       # 12 hours
```

---

## Common Modifications

### Change Detection Strategy

**File**: `detector/detector.py`

```python
def _calculate_z_score(self, value, mean, stddev):
    # Modify z-score calculation here
    if stddev == 0:
        return 0.0 if value == mean else float('inf')
    return (value - mean) / stddev
```

### Add New Alert Type

**File**: `detector/notifier.py`

```python
def alert_custom_event(self, event_data):
    message = f"🔔 *CUSTOM EVENT*\n{event_data}"
    return self._send_slack_message(message, color="#0099FF")
```

### Add Custom Metrics to Dashboard

**File**: `detector/dashboard.py`

Update `_get_metrics_json()`:
```python
metrics['custom_value'] = your_calculation()
```

Update HTML template to display:
```html
<div class="card">
    <h2>Custom Metric</h2>
    <div class="value" id="custom"></div>
</div>

<!-- In JavaScript -->
document.getElementById('custom').textContent = metrics.custom_value;
```

---

## Testing Guidelines

### Unit Tests (To Be Added)

```python
# Example structure for tests/
tests/
├── test_baseline.py
├── test_detector.py
├── test_monitor.py
└── test_blocker.py
```

### Integration Testing

```bash
# Start stack
docker-compose up -d

# Run test traffic generator
python tests/generate_traffic.py

# Monitor results
docker logs -f hng-detector

# Verify blocks
docker exec hng-detector sudo iptables -L -n
```

---

## Code Style

### Python Standards

- **PEP 8** compliant
- **Type hints** for function parameters (optional but encouraged)
- **Docstrings** for all classes and public methods
- **Logging** instead of print statements

### Example:

```python
def check_per_ip_anomaly(
    self, 
    ip: str, 
    current_rate: float, 
    baseline_mean: float,
    baseline_stddev: float
) -> Tuple[bool, Optional[str], float, float]:
    """
    Check if a per-IP rate is anomalous.
    
    Args:
        ip: Source IP address
        current_rate: Current request rate (req/s)
        baseline_mean: Baseline mean from rolling window
        baseline_stddev: Baseline stddev from rolling window
    
    Returns:
        (is_anomalous, condition_fired, z_score, rate_mult_check)
    """
    # Implementation
```

---

## Debugging Tips

### Enable Debug Logging

```bash
# In config.yaml
logging:
  level: "DEBUG"
```

Or via environment:
```bash
export LOG_LEVEL=DEBUG
docker-compose restart detector
```

### Debug Specific Component

Add breakpoints in Python:
```python
import pdb; pdb.set_trace()
```

Run detector locally:
```bash
python detector/main.py
```

### Monitor Internals

```bash
# Watch detector state (run from another terminal)
watch -n 1 'docker exec hng-detector sudo iptables -L -n | grep DROP'

# Watch baseline updates
docker logs hng-detector | grep "baseline_recalc"
```

---

## Performance Profiling

### Memory Profiling

```bash
# Install memory profiler
pip install memory-profiler

# Run with profiling
python -m memory_profiler detector/main.py
```

### CPU Profiling

```bash
# Install cProfile (built-in)
python -m cProfile -s cumtime detector/main.py
```

---

## Deployment Checklist

Before pushing to production:

- [ ] All Python files pass linting (pylint, flake8)
- [ ] All required dependencies in requirements.txt
- [ ] Security audit: no hardcoded secrets
- [ ] Config.yaml uses environment variables
- [ ] Dockerfile optimized (multi-stage if needed)
- [ ] docker-compose.yml uses healthy volumes
- [ ] README updated with any changes
- [ ] Architecture docs updated
- [ ] All modules logged and commented
- [ ] Error handling for edge cases
- [ ] Performance tested under load

---

## Common Issues & Solutions

### Issue: "Module not found" error

**Solution:**
```bash
# Ensure all modules are in detector/
ls detector/*.py

# Check __init__.py exists
test -f detector/__init__.py && echo "Found"

# Verify imports in main.py
grep "^from" detector/main.py
```

### Issue: Baseline doesn't update

**Solution:**
```bash
# Check baseline recalc logs
docker logs hng-detector | grep "recalc"

# Verify log file is being written to
docker exec hng-nginx wc -l /var/log/nginx/hng-access.log

# Check baseline_recalc_interval in config
grep "baseline_recalc_interval" config.yaml
```

### Issue: iptables rules not persisting

**Solution:**
```bash
# iptables rules are in-memory; use iptables-persistent for persistence
# This is not needed for containers but useful on host

# For container, reapply rules on restart:
# Consider adding a startup script to apply saved rules
```

---

## Future Features

- [ ] Machine learning baseline (LSTM)
- [ ] IP reputation service integration
- [ ] Geo-blocking
- [ ] Rate limiting (soft before hard block)
- [ ] Distributed logging (ELK/Datadog)
- [ ] Web UI alerts and notifications
- [ ] Admin dashboard for rule management
- [ ] Webhook integration for custom actions
- [ ] Kubernetes manifests
- [ ] Prometheus metrics export

---

## Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feat/amazing-feature`)
3. Commit changes (`git commit -am 'Add amazing feature'`)
4. Push to branch (`git push origin feat/amazing-feature`)
5. Open a Pull Request

---

## License

This project is part of HNG Internship Stage 3 - DevOps Track.

---

## Support

For issues, questions, or suggestions:
- Create a GitHub issue
- Contact: internship@hng.tech
