"""
Baseline calculation module.
Maintains a rolling 30-minute baseline per hour slot.
Recalculates every 60 seconds using per-second request counts.
"""

import time
from collections import defaultdict, deque
from statistics import mean, stdev
import logging

logger = logging.getLogger(__name__)


class BaselineCalculator:
    def __init__(self, window_size_seconds=1800, recalc_interval=60):
        """
        Args:
            window_size_seconds: Rolling window size in seconds (default 30 minutes)
            recalc_interval: Recalculation interval in seconds (default 60)
        """
        self.window_size = window_size_seconds
        self.recalc_interval = recalc_interval
        
        # Per-hour per-second request counts: {hour: deque([count, count, ...])}
        self.per_hour_data = defaultdict(lambda: deque(maxlen=3600))  # Max 1 hour = 3600 seconds
        
        # Global per-second counts (for global baseline): {hour: deque}
        self.global_hour_data = defaultdict(lambda: deque(maxlen=3600))
        
        # Per-IP per-hour data: {ip: {hour: deque}}
        self.per_ip_hour_data = defaultdict(lambda: defaultdict(lambda: deque(maxlen=3600)))
        
        # Last recalculation time
        self.last_recalc = time.time()
        
        # Cached baselines (recalculated every 60 seconds)
        self.cached_baselines = {
            'global': {'mean': 0, 'stddev': 0},
            'per_ip': {}  # {ip: {'mean': x, 'stddev': y}}
        }
        
        logger.info("BaselineCalculator initialized with window_size=%ds, recalc_interval=%ds",
                    window_size_seconds, recalc_interval)
    
    def get_current_hour(self):
        """Returns the current hour as an integer (0-23)."""
        return int(time.time()) // 3600
    
    def add_request_count(self, per_second_counts_global, per_second_counts_per_ip):
        """
        Called every second with aggregate counts for that second.
        
        Args:
            per_second_counts_global: int - total requests in the current second
            per_second_counts_per_ip: dict - {ip: count} for current second
        """
        current_hour = self.get_current_hour()
        
        # Add global count
        self.global_hour_data[current_hour].append(per_second_counts_global)
        
        # Add per-IP counts
        for ip, count in per_second_counts_per_ip.items():
            self.per_ip_hour_data[ip][current_hour].append(count)
        
        # Recalculate baselines if interval has passed
        if time.time() - self.last_recalc >= self.recalc_interval:
            self.recalculate_baselines()
    
    def recalculate_baselines(self):
        """Recalculate baselines from rolling window data."""
        current_hour = self.get_current_hour()
        self.last_recalc = time.time()
        
        # Global baseline: prefer current hour if available, fall back to previous hour
        global_mean, global_stddev = self._calculate_baseline_for_window(
            self.global_hour_data, current_hour
        )
        self.cached_baselines['global'] = {
            'mean': global_mean,
            'stddev': global_stddev
        }
        
        # Per-IP baselines
        self.cached_baselines['per_ip'] = {}
        for ip in self.per_ip_hour_data:
            ip_mean, ip_stddev = self._calculate_baseline_for_window(
                self.per_ip_hour_data[ip], current_hour
            )
            self.cached_baselines['per_ip'][ip] = {
                'mean': ip_mean,
                'stddev': ip_stddev
            }
        
        logger.debug(
            "Baselines recalculated | global_mean=%.2f | global_stddev=%.2f",
            global_mean, global_stddev
        )
    
    def _calculate_baseline_for_window(self, hour_data_dict, current_hour):
        """
        Calculate mean and stddev from the rolling 30-minute window.
        Prefer current hour; if insufficient data, use previous hour.
        Enforce floor values to prevent false negatives.
        
        Args:
            hour_data_dict: dict of {hour: deque of per-second counts}
            current_hour: current hour integer
            
        Returns:
            (mean, stddev) tuple; floor at 1.0 for mean, 0.1 for stddev
        """
        # Try current hour first
        if current_hour in hour_data_dict and len(hour_data_dict[current_hour]) > 0:
            data = list(hour_data_dict[current_hour])
        # Fall back to previous hour if current has no data
        elif (current_hour - 1) in hour_data_dict and len(hour_data_dict[current_hour - 1]) > 0:
            data = list(hour_data_dict[current_hour - 1])
        else:
            # No data available
            return 1.0, 0.1
        
        if len(data) < 2:
            # Not enough data for stddev
            return float(mean(data)), 0.1
        
        calc_mean = mean(data)
        calc_stddev = stdev(data)
        
        # Floor values to prevent false negatives
        effective_mean = max(calc_mean, 1.0)
        effective_stddev = max(calc_stddev, 0.1)
        
        return effective_mean, effective_stddev
    
    def get_global_baseline(self):
        """Return cached global baseline."""
        return self.cached_baselines['global'].copy()
    
    def get_ip_baseline(self, ip):
        """Return cached baseline for a specific IP."""
        return self.cached_baselines['per_ip'].get(ip, {'mean': 1.0, 'stddev': 0.1}).copy()
    
    def get_all_baselines(self):
        """Return all cached baselines."""
        return self.cached_baselines.copy()
    
    def cleanup_old_hours(self, keep_hours=2):
        """Remove data older than keep_hours to prevent memory bloat."""
        current_hour = self.get_current_hour()
        cutoff_hour = current_hour - keep_hours
        
        # Clean global data
        hours_to_remove = [h for h in self.global_hour_data if h < cutoff_hour]
        for h in hours_to_remove:
            del self.global_hour_data[h]
        
        # Clean per-IP data
        for ip in list(self.per_ip_hour_data.keys()):
            hours_to_remove = [h for h in self.per_ip_hour_data[ip] if h < cutoff_hour]
            for h in hours_to_remove:
                del self.per_ip_hour_data[ip][h]
            # Remove IP entirely if no data left
            if not self.per_ip_hour_data[ip]:
                del self.per_ip_hour_data[ip]
