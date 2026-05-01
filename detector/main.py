"""
HNG Anomaly Detection Engine - Main Entry Point
Continuously monitors Nginx logs, detects anomalies, blocks IPs, and sends Slack alerts.
"""

import yaml
import logging
import time
import os
import sys
import signal
import threading
from pathlib import Path

from monitor import LogMonitor
from baseline import BaselineCalculator
from detector import AnomalyDetector
from blocker import IPBlocker
from unbanner import AutoUnbanner
from notifier import Notifier
from dashboard import Dashboard

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/hng-detector/detector.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class AnomalyDetectionEngine:
    def __init__(self, config_path='config.yaml'):
        """Initialize the anomaly detection engine."""
        self.config = self._load_config(config_path)
        self.running = False
        
        # Initialize components
        self.monitor = LogMonitor(
            log_path=self.config['nginx']['log_path'],
            window_seconds=self.config['windows']['short_window']
        )
        
        self.baseline_calc = BaselineCalculator(
            window_size_seconds=self.config['windows']['baseline_window'],
            recalc_interval=self.config['windows']['baseline_recalc_interval']
        )
        
        self.detector = AnomalyDetector(
            z_score_threshold=self.config['detection']['z_score_threshold'],
            rate_multiplier=self.config['detection']['rate_multiplier'],
            error_rate_multiplier=self.config['detection']['error_rate_multiplier'],
            global_rate_multiplier=self.config['detection']['global_anomaly_multiplier']
        )
        
        self.blocker = IPBlocker()
        
        self.unbanner = AutoUnbanner(
            backoff_schedule=self.config['unbanner']['schedule'],
            permanent_after=self.config['unbanner']['permanent_after']
        )
        
        self.notifier = Notifier(
            webhook_url=os.getenv('SLACK_WEBHOOK_URL', self.config['slack']['webhook_url']),
            timeout=self.config['slack']['timeout']
        )
        
        self.dashboard = Dashboard(
            host=self.config['dashboard']['host'],
            port=self.config['dashboard']['port']
        )
        self.dashboard.monitor = self.monitor
        self.dashboard.baseline_calc = self.baseline_calc
        self.dashboard.blocker = self.blocker
        self.dashboard.detector = self.detector
        
        # Create log directory if it doesn't exist
        log_dir = Path(self.config['audit']['log_file']).parent
        log_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("AnomalyDetectionEngine initialized successfully")
    
    def _load_config(self, config_path):
        """Load configuration from YAML file."""
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info("Configuration loaded from %s", config_path)
            return config
        except FileNotFoundError:
            logger.error("Configuration file not found: %s", config_path)
            raise
        except yaml.YAMLError as e:
            logger.error("Failed to parse configuration: %s", e)
            raise
    
    def _audit_log(self, action, ip=None, condition=None, rate=None, baseline=None, duration=None):
        """Write audit log entry."""
        try:
            timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            entry = {
                'timestamp': timestamp,
                'action': action,
                'ip': ip or 'N/A',
                'condition': condition or 'N/A',
                'rate': f"{rate:.2f}" if rate is not None else 'N/A',
                'baseline': f"{baseline:.2f}" if baseline is not None else 'N/A',
                'duration': f"{duration}m" if duration is not None else 'N/A'
            }
            
            with open(self.config['audit']['log_file'], 'a') as f:
                f.write(f"[{timestamp}] {action}")
                if ip:
                    f.write(f" | IP:{ip}")
                if condition:
                    f.write(f" | {condition}")
                if rate is not None:
                    f.write(f" | rate:{rate:.2f}")
                if baseline is not None:
                    f.write(f" | baseline:{baseline:.2f}")
                if duration is not None:
                    f.write(f" | duration:{duration}m")
                f.write("\n")
        
        except Exception as e:
            logger.error("Failed to write audit log: %s", e)
    
    def run(self):
        """Run the main detection loop."""
        self.running = True
        logger.info("Starting anomaly detection engine...")
        
        # Start dashboard in background thread
        dashboard_thread = threading.Thread(target=self.dashboard.run, kwargs={'debug': False}, daemon=True)
        dashboard_thread.start()
        logger.info("Dashboard started on %s:%d", self.config['dashboard']['host'], self.config['dashboard']['port'])
        
        # Open log file
        self.monitor.open_log()
        
        # Main detection loop
        last_baseline_recalc = time.time()
        last_unban_check = time.time()
        last_second = int(time.time())
        
        try:
            while self.running:
                now = time.time()
                current_second = int(now)
                
                # Read new log lines
                for log_entry in self.monitor.read_log_lines():
                    pass  # Monitor internally aggregates counts
                
                # Every second: update baseline calculator and check for anomalies
                if current_second > last_second:
                    last_second = current_second
                    
                    # Aggregate counts for this second
                    global_count = self.monitor.current_second_global_count
                    per_ip_counts = dict(self.monitor.current_second_per_ip)
                    
                    # Add to baseline calculator
                    self.baseline_calc.add_request_count(global_count, per_ip_counts)
                    
                    # Get baselines
                    global_baseline = self.baseline_calc.get_global_baseline()
                    
                    # Check per-IP anomalies
                    for ip in self.monitor.get_active_ips():
                        ip_rate = self.monitor.get_per_ip_rate(ip)
                        ip_baseline = self.baseline_calc.get_ip_baseline(ip)
                        ip_error_rate = self.monitor.get_per_ip_error_rate(ip)
                        global_error_rate = self.monitor.get_global_error_rate()
                        
                        is_anomaly, condition, z_score, rate_mult = self.detector.check_per_ip_anomaly(
                            ip, ip_rate,
                            ip_baseline['mean'], ip_baseline['stddev'],
                            ip_error_rate, global_error_rate
                        )
                        
                        if is_anomaly and not self.blocker.is_blocked(ip):
                            # Block the IP
                            success = self.blocker.block_ip(ip, condition)
                            if success:
                                self.unbanner.add_ip_to_schedule(ip)
                                
                                # Calculate ban duration (first attempt = 10 minutes)
                                duration_minutes = self.config['unbanner']['schedule'][0] // 60
                                
                                # Send Slack alert
                                self.notifier.alert_ban(
                                    ip, condition, ip_rate,
                                    ip_baseline['mean'], duration_minutes
                                )
                                
                                # Audit log
                                self._audit_log(
                                    'BAN', ip=ip, condition=condition,
                                    rate=ip_rate, baseline=ip_baseline['mean'],
                                    duration=duration_minutes
                                )
                    
                    # Check global anomaly
                    global_rate = self.monitor.get_global_rate()
                    is_global_anomaly, global_condition, global_mult = self.detector.check_global_anomaly(
                        global_rate,
                        global_baseline['mean'], global_baseline['stddev']
                    )
                    
                    if is_global_anomaly:
                        # Alert only (no blocking)
                        self.notifier.alert_global_anomaly(
                            global_condition, global_rate, global_baseline['mean']
                        )
                        self._audit_log(
                            'GLOBAL_ANOMALY', condition=global_condition,
                            rate=global_rate, baseline=global_baseline['mean']
                        )
                
                # Every 60 seconds: check for IPs to unban
                if now - last_unban_check >= 60:
                    last_unban_check = now
                    
                    ips_to_unban = self.unbanner.get_ips_ready_for_unban()
                    for ip in ips_to_unban:
                        # Unblock the IP
                        success = self.blocker.unblock_ip(ip)
                        if success:
                            attempt = self.unbanner.get_unban_attempt_count(ip)
                            schedule = self.config['unbanner']['schedule']
                            
                            if attempt < len(schedule):
                                reason = f"Backoff schedule - attempt {attempt}/{len(schedule)}"
                            else:
                                reason = "Ban schedule exhausted"
                            
                            self.notifier.alert_unban(ip, reason)
                            self._audit_log('UNBAN', ip=ip)
                            
                            self.unbanner.mark_unbanned(ip)
                
                # Every 60 seconds: log baseline recalculation
                if now - last_baseline_recalc >= 60:
                    last_baseline_recalc = now
                    global_baseline = self.baseline_calc.get_global_baseline()
                    self._audit_log(
                        'BASELINE_RECALC',
                        baseline=global_baseline['mean']
                    )
                    logger.info(
                        "Baseline recalculated | mean=%.2f | stddev=%.2f | "
                        "active_ips=%d | blocked_ips=%d",
                        global_baseline['mean'], global_baseline['stddev'],
                        len(self.monitor.get_active_ips()),
                        len(self.blocker.get_blocked_ips())
                    )
                    
                    # Cleanup old data
                    self.baseline_calc.cleanup_old_hours(keep_hours=2)
                
                # Small sleep to prevent busy waiting
                time.sleep(0.1)
        
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        except Exception as e:
            logger.error("Fatal error in detection loop: %s", e, exc_info=True)
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Gracefully shutdown the engine."""
        logger.info("Shutting down anomaly detection engine...")
        self.running = False
        self.monitor.close_log()
        
        # Unblock all IPs on shutdown (optional - you might want to keep bans)
        # blocked_ips = self.blocker.get_blocked_ips()
        # for ip in blocked_ips:
        #     self.blocker.unblock_ip(ip)
        
        logger.info("Anomaly detection engine shut down")


def signal_handler(signum, frame):
    """Handle SIGTERM and SIGINT."""
    logger.info("Received signal %d", signum)
    sys.exit(0)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        config_path = os.getenv('CONFIG_PATH', 'config.yaml')
        engine = AnomalyDetectionEngine(config_path)
        engine.run()
    except Exception as e:
        logger.error("Failed to start engine: %s", e, exc_info=True)
        sys.exit(1)
