"""
IP blocking module.
Manages iptables DROP rules for detected anomalies.
Provides per-IP blocking and tracking.
"""

import subprocess
import logging
import time

logger = logging.getLogger(__name__)


class IPBlocker:
    def __init__(self):
        """Initialize the IP blocker."""
        self.blocked_ips = {}  # {ip: {'blocked_at': timestamp, 'reason': str}}
        logger.info("IPBlocker initialized")
    
    def block_ip(self, ip, reason):
        """
        Block an IP using iptables DROP rule.
        
        Args:
            ip: IP address to block
            reason: Reason for blocking (stored for audit)
            
        Returns:
            True if successfully blocked, False otherwise
        """
        if ip in self.blocked_ips:
            logger.debug("IP %s already blocked", ip)
            return True
        
        try:
            # Add iptables DROP rule for this IP
            cmd = ['sudo', 'iptables', '-I', 'INPUT', '-s', ip, '-j', 'DROP']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                logger.error(
                    "Failed to block IP %s | Error: %s",
                    ip, result.stderr
                )
                return False
            
            self.blocked_ips[ip] = {
                'blocked_at': time.time(),
                'reason': reason
            }
            
            logger.info("Blocked IP %s | Reason: %s", ip, reason)
            return True
        
        except subprocess.TimeoutExpired:
            logger.error("Timeout blocking IP %s", ip)
            return False
        except Exception as e:
            logger.error("Error blocking IP %s: %s", ip, e)
            return False
    
    def unblock_ip(self, ip):
        """
        Unblock an IP by removing the iptables DROP rule.
        
        Args:
            ip: IP address to unblock
            
        Returns:
            True if successfully unblocked, False otherwise
        """
        if ip not in self.blocked_ips:
            logger.debug("IP %s not in blocked list", ip)
            return True
        
        try:
            # Remove iptables DROP rule for this IP
            cmd = ['sudo', 'iptables', '-D', 'INPUT', '-s', ip, '-j', 'DROP']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode != 0:
                logger.error(
                    "Failed to unblock IP %s | Error: %s",
                    ip, result.stderr
                )
                return False
            
            del self.blocked_ips[ip]
            logger.info("Unblocked IP %s", ip)
            return True
        
        except subprocess.TimeoutExpired:
            logger.error("Timeout unblocking IP %s", ip)
            return False
        except Exception as e:
            logger.error("Error unblocking IP %s: %s", ip, e)
            return False
    
    def get_blocked_ips(self):
        """Return list of currently blocked IPs."""
        return list(self.blocked_ips.keys())
    
    def get_block_info(self, ip):
        """Return block info for an IP if blocked, None otherwise."""
        return self.blocked_ips.get(ip)
    
    def is_blocked(self, ip):
        """Check if an IP is currently blocked."""
        return ip in self.blocked_ips
