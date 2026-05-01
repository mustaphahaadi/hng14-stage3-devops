"""
Notification module.
Sends Slack alerts for bans, unbans, and global anomalies.
"""

import requests
import logging
import time
import json

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, webhook_url, timeout=10):
        """
        Args:
            webhook_url: Slack webhook URL
            timeout: Request timeout in seconds
        """
        self.webhook_url = webhook_url
        self.timeout = timeout
        
        # Track recent alerts to avoid spam (10 seconds min between identical alerts)
        self.alert_cache = {}  # {key: last_alert_time}
        
        logger.info("Notifier initialized | webhook_configured=%s", bool(webhook_url))
    
    def _send_slack_message(self, message_text, color="#FF0000"):
        """
        Send a message to Slack.
        
        Args:
            message_text: Plain text message
            color: Hex color for the attachment
            
        Returns:
            True if successful, False otherwise
        """
        if not self.webhook_url or self.webhook_url.startswith("${"):
            logger.warning("Slack webhook not configured; skipping alert")
            return False
        
        try:
            payload = {
                "attachments": [
                    {
                        "color": color,
                        "text": message_text,
                        "ts": int(time.time())
                    }
                ]
            }
            
            response = requests.post(
                self.webhook_url,
                json=payload,
                timeout=self.timeout
            )
            
            if response.status_code != 200:
                logger.error(
                    "Slack webhook failed | status=%d | response=%s",
                    response.status_code, response.text
                )
                return False
            
            logger.debug("Slack alert sent successfully")
            return True
        
        except requests.Timeout:
            logger.error("Slack webhook timeout")
            return False
        except Exception as e:
            logger.error("Error sending Slack alert: %s", e)
            return False
    
    def _should_alert(self, cache_key, min_interval=10):
        """
        Check if we should send this alert (avoid spam).
        
        Args:
            cache_key: Unique key for this alert type
            min_interval: Minimum seconds between identical alerts
            
        Returns:
            True if enough time has passed since last similar alert
        """
        now = time.time()
        last_time = self.alert_cache.get(cache_key, 0)
        
        if now - last_time >= min_interval:
            self.alert_cache[cache_key] = now
            return True
        
        return False
    
    def alert_ban(self, ip, condition, rate, baseline, duration_minutes):
        """
        Alert on IP ban.
        
        Args:
            ip: IP address being banned
            condition: Condition that triggered the ban
            rate: Current request rate
            baseline: Baseline request rate
            duration_minutes: Ban duration in minutes
        """
        cache_key = f"ban:{ip}"
        if not self._should_alert(cache_key):
            logger.debug("Skipping duplicate ban alert for IP %s", ip)
            return False
        
        message = (
            f"🚫 *IP BANNED*\n"
            f"IP: `{ip}`\n"
            f"Condition: {condition}\n"
            f"Current Rate: {rate:.2f} req/s\n"
            f"Baseline: {baseline:.2f} req/s\n"
            f"Ban Duration: {duration_minutes} minutes\n"
            f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}"
        )
        
        return self._send_slack_message(message, color="#FF0000")
    
    def alert_unban(self, ip, reason=""):
        """
        Alert on IP unban.
        
        Args:
            ip: IP address being unbanned
            reason: Reason for unban (e.g., "Backoff schedule - attempt 1/3")
        """
        cache_key = f"unban:{ip}"
        if not self._should_alert(cache_key):
            logger.debug("Skipping duplicate unban alert for IP %s", ip)
            return False
        
        message = (
            f"✅ *IP UNBANNED*\n"
            f"IP: `{ip}`\n"
            f"Reason: {reason}\n"
            f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}"
        )
        
        return self._send_slack_message(message, color="#00FF00")
    
    def alert_global_anomaly(self, condition, rate, baseline):
        """
        Alert on global anomaly (no IP block, just notification).
        
        Args:
            condition: Condition that triggered the alert
            rate: Current global request rate
            baseline: Baseline global request rate
        """
        cache_key = "global_anomaly"
        if not self._should_alert(cache_key, min_interval=30):  # Less spam for global
            logger.debug("Skipping duplicate global anomaly alert")
            return False
        
        message = (
            f"⚠️ *GLOBAL ANOMALY DETECTED*\n"
            f"Condition: {condition}\n"
            f"Current Rate: {rate:.2f} req/s\n"
            f"Baseline: {baseline:.2f} req/s\n"
            f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}"
        )
        
        return self._send_slack_message(message, color="#FFAA00")
    
    def clear_cache(self):
        """Clear the alert cache."""
        self.alert_cache = {}
