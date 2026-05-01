"""
Anomaly detection module.
Implements z-score and rate multiplier thresholds.
Detects per-IP and global anomalies.
"""

import logging
import time

logger = logging.getLogger(__name__)


class AnomalyDetector:
    def __init__(self, z_score_threshold=3.0, rate_multiplier=5.0, 
                 error_rate_multiplier=3.0, global_rate_multiplier=5.0):
        """
        Args:
            z_score_threshold: Z-score threshold (default 3.0)
            rate_multiplier: Rate multiplier threshold for per-IP (default 5.0)
            error_rate_multiplier: Error rate multiplier threshold (default 3.0)
            global_rate_multiplier: Rate multiplier for global anomaly (default 5.0)
        """
        self.z_score_threshold = z_score_threshold
        self.rate_multiplier = rate_multiplier
        self.error_rate_multiplier = error_rate_multiplier
        self.global_rate_multiplier = global_rate_multiplier
        
        # Track tightened thresholds for IPs with high error rates
        self.tightened_ips = {}  # {ip: {'z_score': x, 'rate_mult': y, 'until': timestamp}}
        
        logger.info(
            "AnomalyDetector initialized | z_threshold=%.1f | rate_mult=%.1f | "
            "error_mult=%.1f | global_mult=%.1f",
            z_score_threshold, rate_multiplier, error_rate_multiplier, global_rate_multiplier
        )
    
    def _calculate_z_score(self, value, mean, stddev):
        """Calculate Z-score: (value - mean) / stddev."""
        if stddev == 0:
            return 0.0 if value == mean else float('inf')
        return (value - mean) / stddev
    
    def _check_tightened_threshold(self, ip):
        """
        Check if this IP has tightened thresholds due to high error rate.
        Clean up expired entries.
        Returns: (z_threshold, rate_mult, is_tightened)
        """
        now = time.time()
        
        if ip in self.tightened_ips:
            entry = self.tightened_ips[ip]
            if entry['until'] > now:
                # Still tightened
                return entry['z_score'], entry['rate_mult'], True
            else:
                # Expired, remove
                del self.tightened_ips[ip]
        
        return self.z_score_threshold, self.rate_multiplier, False
    
    def check_per_ip_anomaly(self, ip, current_rate, baseline_mean, baseline_stddev, 
                             current_error_rate, baseline_error_rate):
        """
        Check if a per-IP rate is anomalous.
        
        Args:
            ip: Source IP address
            current_rate: Current request rate (req/s) for this IP
            baseline_mean: Baseline mean from rolling window
            baseline_stddev: Baseline stddev from rolling window
            current_error_rate: Current error rate for this IP
            baseline_error_rate: Baseline error rate for this IP
        
        Returns:
            (is_anomalous, condition_fired, z_score, rate_mult_check)
        """
        if baseline_mean == 0:
            baseline_mean = 1.0
        
        # Check for high error rate and tighten thresholds if needed
        if baseline_error_rate > 0 and current_error_rate > 0:
            error_ratio = current_error_rate / baseline_error_rate
            if error_ratio > self.error_rate_multiplier:
                # Tighten thresholds for this IP for 5 minutes
                if ip not in self.tightened_ips or self.tightened_ips[ip]['until'] < time.time():
                    tightened_z = self.z_score_threshold * 0.6  # 60% of normal threshold
                    tightened_mult = self.rate_multiplier * 0.5  # 50% of normal multiplier
                    self.tightened_ips[ip] = {
                        'z_score': tightened_z,
                        'rate_mult': tightened_mult,
                        'until': time.time() + 300  # 5 minutes
                    }
                    logger.info(
                        "Tightened thresholds for IP %s | error_rate=%.2f | "
                        "baseline_error=%.2f | ratio=%.2f",
                        ip, current_error_rate, baseline_error_rate, error_ratio
                    )
        
        z_threshold, rate_mult, is_tightened = self._check_tightened_threshold(ip)
        
        # Calculate Z-score
        z_score = self._calculate_z_score(current_rate, baseline_mean, baseline_stddev)
        
        # Check Z-score threshold
        if z_score > z_threshold:
            logger.info(
                "Per-IP Z-score anomaly | IP=%s | z=%.2f | threshold=%.1f | "
                "rate=%.2f | baseline=%.2f | tightened=%s",
                ip, z_score, z_threshold, current_rate, baseline_mean, is_tightened
            )
            return True, f"z_score (z={z_score:.2f})", z_score, 0.0
        
        # Check rate multiplier threshold
        rate_mult_check = current_rate / baseline_mean if baseline_mean > 0 else 0.0
        if rate_mult_check > rate_mult:
            logger.info(
                "Per-IP rate multiplier anomaly | IP=%s | mult=%.2f | threshold=%.1f | "
                "rate=%.2f | baseline=%.2f | tightened=%s",
                ip, rate_mult_check, rate_mult, current_rate, baseline_mean, is_tightened
            )
            return True, f"rate_multiplier (mult={rate_mult_check:.2f})", z_score, rate_mult_check
        
        return False, None, z_score, rate_mult_check
    
    def check_global_anomaly(self, current_rate, baseline_mean, baseline_stddev):
        """
        Check if global rate is anomalous.
        Global anomalies only trigger alerts (no blocking).
        
        Args:
            current_rate: Current global request rate (req/s)
            baseline_mean: Baseline mean from rolling window
            baseline_stddev: Baseline stddev from rolling window
        
        Returns:
            (is_anomalous, condition_fired, rate_mult_check)
        """
        if baseline_mean == 0:
            baseline_mean = 1.0
        
        # Check rate multiplier (global only uses rate multiplier, not z-score)
        rate_mult_check = current_rate / baseline_mean if baseline_mean > 0 else 0.0
        if rate_mult_check > self.global_rate_multiplier:
            logger.info(
                "Global rate multiplier anomaly | mult=%.2f | threshold=%.1f | "
                "rate=%.2f | baseline=%.2f",
                rate_mult_check, self.global_rate_multiplier, current_rate, baseline_mean
            )
            return True, f"global_rate_multiplier (mult={rate_mult_check:.2f})", rate_mult_check
        
        return False, None, rate_mult_check
