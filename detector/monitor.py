"""
Log monitoring module.
Tails Nginx access log line by line, parses JSON, and extracts metrics.
Uses deques for per-second aggregation and sliding window tracking.
"""

import json
import time
from collections import deque, defaultdict
import logging

logger = logging.getLogger(__name__)


class LogMonitor:
    def __init__(self, log_path, window_seconds=60):
        """
        Args:
            log_path: Path to Nginx JSON access log
            window_seconds: Sliding window size in seconds (default 60)
        """
        self.log_path = log_path
        self.window_seconds = window_seconds
        
        # Sliding window for per-IP request counts: {ip: deque of (timestamp, count)}
        self.per_ip_window = defaultdict(deque)
        
        # Sliding window for global request counts: deque of (timestamp, count)
        self.global_window = deque()
        
        # Per-IP error tracking: {ip: deque of (timestamp, count)}
        self.per_ip_errors = defaultdict(deque)
        
        # Global errors: deque of (timestamp, count)
        self.global_errors = deque()
        
        # Current second aggregation
        self.current_second = int(time.time())
        self.current_second_global_count = 0
        self.current_second_per_ip = defaultdict(int)
        self.current_second_global_errors = 0
        self.current_second_per_ip_errors = defaultdict(int)
        
        # File handle
        self.log_file = None
        self.file_position = 0
        
        logger.info("LogMonitor initialized for %s with window=%ds", log_path, window_seconds)
    
    def open_log(self):
        """Open the log file and seek to end."""
        try:
            self.log_file = open(self.log_path, 'r')
            self.log_file.seek(0, 2)  # Seek to end
            self.file_position = self.log_file.tell()
            logger.info("Opened log file at position %d", self.file_position)
        except FileNotFoundError:
            logger.warning("Log file not found: %s. Will retry on next read.", self.log_path)
            self.log_file = None
    
    def read_log_lines(self):
        """
        Read new lines from log file since last read.
        Aggregate counts per second and update sliding windows.
        
        Yields:
            Parsed log entries as dicts
        """
        if self.log_file is None:
            self.open_log()
            if self.log_file is None:
                return
        
        try:
            lines = self.log_file.readlines()
            if not lines:
                return
            
            now = time.time()
            current_second = int(now)
            
            # Flush the previous second's aggregates when we move to a new second
            if current_second > self.current_second:
                self._flush_current_second(self.current_second)
                self.current_second = current_second
                self.current_second_global_count = 0
                self.current_second_per_ip = defaultdict(int)
                self.current_second_global_errors = 0
                self.current_second_per_ip_errors = defaultdict(int)
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                try:
                    entry = json.loads(line)
                    yield entry
                    
                    # Extract metrics
                    source_ip = entry.get('source_ip', 'unknown')
                    status = entry.get('status', 0)
                    
                    # Count total requests
                    self.current_second_global_count += 1
                    self.current_second_per_ip[source_ip] += 1
                    
                    # Count errors (4xx, 5xx)
                    if 400 <= status < 600:
                        self.current_second_global_errors += 1
                        self.current_second_per_ip_errors[source_ip] += 1
                
                except json.JSONDecodeError as e:
                    logger.debug("Failed to parse JSON log line: %s | Error: %s", line[:100], e)
                except Exception as e:
                    logger.warning("Error processing log entry: %s", e)
        
        except Exception as e:
            logger.error("Error reading log file: %s", e)
            self.log_file = None
    
    def _flush_current_second(self, second_timestamp):
        """Store the aggregated second's data in sliding windows."""
        # Add to global window
        self.global_window.append((second_timestamp, self.current_second_global_count))
        self.global_errors.append((second_timestamp, self.current_second_global_errors))
        
        # Add to per-IP windows
        for ip, count in self.current_second_per_ip.items():
            self.per_ip_window[ip].append((second_timestamp, count))
        
        for ip, count in self.current_second_per_ip_errors.items():
            self.per_ip_errors[ip].append((second_timestamp, count))
        
        # Clean up old entries outside the window
        self._cleanup_windows(second_timestamp)
    
    def _cleanup_windows(self, current_second):
        """Remove entries older than window_seconds."""
        cutoff = current_second - self.window_seconds
        
        # Clean global window
        while self.global_window and self.global_window[0][0] < cutoff:
            self.global_window.popleft()
        
        while self.global_errors and self.global_errors[0][0] < cutoff:
            self.global_errors.popleft()
        
        # Clean per-IP windows
        for ip in list(self.per_ip_window.keys()):
            while self.per_ip_window[ip] and self.per_ip_window[ip][0][0] < cutoff:
                self.per_ip_window[ip].popleft()
            if not self.per_ip_window[ip]:
                del self.per_ip_window[ip]
        
        for ip in list(self.per_ip_errors.keys()):
            while self.per_ip_errors[ip] and self.per_ip_errors[ip][0][0] < cutoff:
                self.per_ip_errors[ip].popleft()
            if not self.per_ip_errors[ip]:
                del self.per_ip_errors[ip]
    
    def get_global_rate(self):
        """Return current global request rate (requests/second) from sliding window."""
        if not self.global_window:
            return 0.0
        return sum(count for _, count in self.global_window) / len(self.global_window)
    
    def get_per_ip_rate(self, ip):
        """Return current rate for a specific IP (requests/second)."""
        if ip not in self.per_ip_window or not self.per_ip_window[ip]:
            return 0.0
        return sum(count for _, count in self.per_ip_window[ip]) / len(self.per_ip_window[ip])
    
    def get_global_error_rate(self):
        """Return current global error rate from sliding window."""
        if not self.global_errors:
            return 0.0
        return sum(count for _, count in self.global_errors) / len(self.global_errors)
    
    def get_per_ip_error_rate(self, ip):
        """Return current error rate for a specific IP."""
        if ip not in self.per_ip_errors or not self.per_ip_errors[ip]:
            return 0.0
        return sum(count for _, count in self.per_ip_errors[ip]) / len(self.per_ip_errors[ip])
    
    def get_active_ips(self):
        """Return list of IPs with traffic in the current window."""
        return list(self.per_ip_window.keys())
    
    def close_log(self):
        """Close the log file."""
        if self.log_file:
            self.log_file.close()
            self.log_file = None
