"""
Auto-unban module.
Manages automatic unban of IPs using a backoff schedule.
Sends notifications on each unban.
"""

import time
import logging

logger = logging.getLogger(__name__)


class AutoUnbanner:
    def __init__(self, backoff_schedule=[600, 1800, 7200], permanent_after=43200):
        """
        Args:
            backoff_schedule: List of backoff intervals in seconds [10min, 30min, 2hrs]
            permanent_after: After this duration, ban is permanent (seconds, default 12 hours)
        """
        self.backoff_schedule = backoff_schedule  # [600, 1800, 7200]
        self.permanent_after = permanent_after
        
        # Track unban schedule: {ip: {'blocked_at': timestamp, 'unban_attempts': int}}
        self.unban_schedule = {}
        
        logger.info(
            "AutoUnbanner initialized | schedule=%s | permanent_after=%ds",
            backoff_schedule, permanent_after
        )
    
    def add_ip_to_schedule(self, ip):
        """Add a newly blocked IP to the unban schedule."""
        if ip not in self.unban_schedule:
            self.unban_schedule[ip] = {
                'blocked_at': time.time(),
                'unban_attempts': 0,
                'last_unban_time': None
            }
            logger.info("Added IP %s to unban schedule", ip)
    
    def get_next_unban_time(self, ip):
        """
        Get the next time an IP should be unbanned.
        
        Returns:
            (unban_time, should_be_permanent, unban_attempt_number)
        """
        if ip not in self.unban_schedule:
            return None, False, 0
        
        schedule = self.unban_schedule[ip]
        blocked_at = schedule['blocked_at']
        unban_attempts = schedule['unban_attempts']
        
        time_elapsed = time.time() - blocked_at
        
        # Check if ban should be permanent
        if time_elapsed > self.permanent_after:
            return None, True, unban_attempts
        
        # Get next unban time based on backoff schedule
        if unban_attempts < len(self.backoff_schedule):
            next_unban_interval = self.backoff_schedule[unban_attempts]
            next_unban_time = blocked_at + sum(self.backoff_schedule[:unban_attempts]) + next_unban_interval
            return next_unban_time, False, unban_attempts
        
        # All scheduled unbans exhausted, will be permanent on next check
        return None, False, unban_attempts
    
    def should_unban_now(self, ip):
        """Check if an IP is ready to be unbanned now."""
        if ip not in self.unban_schedule:
            return False
        
        unban_time, is_permanent, _ = self.get_next_unban_time(ip)
        
        if is_permanent:
            return False  # Permanent bans stay
        
        if unban_time is None:
            return False
        
        return time.time() >= unban_time
    
    def mark_unbanned(self, ip):
        """Mark an IP as unbanned and prepare for next unban (if applicable)."""
        if ip not in self.unban_schedule:
            return
        
        schedule = self.unban_schedule[ip]
        schedule['unban_attempts'] += 1
        schedule['last_unban_time'] = time.time()
        
        logger.info(
            "Marked IP %s as unbanned | attempt=%d",
            ip, schedule['unban_attempts']
        )
    
    def get_unban_attempt_count(self, ip):
        """Get the number of unban attempts for an IP."""
        if ip not in self.unban_schedule:
            return 0
        return self.unban_schedule[ip]['unban_attempts']
    
    def remove_ip_from_schedule(self, ip):
        """Remove an IP from the unban schedule (after it's been unbanned permanently)."""
        if ip in self.unban_schedule:
            del self.unban_schedule[ip]
            logger.info("Removed IP %s from unban schedule", ip)
    
    def get_ips_ready_for_unban(self):
        """Return list of IPs that are ready to be unbanned now."""
        ready = [ip for ip in self.unban_schedule if self.should_unban_now(ip)]
        return ready
    
    def get_schedule_info(self):
        """Return info on all IPs in unban schedule."""
        return self.unban_schedule.copy()
