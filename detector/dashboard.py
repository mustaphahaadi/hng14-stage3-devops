"""
Dashboard module.
Provides a live web UI showing banned IPs, metrics, and system info.
"""

from flask import Flask, jsonify, render_template_string
import psutil
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)


class Dashboard:
    def __init__(self, host="0.0.0.0", port=8000):
        """
        Args:
            host: Bind address
            port: Listen port
        """
        self.host = host
        self.port = port
        self.app = Flask(__name__)
        
        # Reference to detector components (will be set by main)
        self.monitor = None
        self.baseline_calc = None
        self.blocker = None
        self.detector = None
        self.start_time = time.time()
        
        self._setup_routes()
        
        logger.info("Dashboard initialized on %s:%d", host, port)
    
    def _setup_routes(self):
        """Setup Flask routes."""
        @self.app.route('/')
        def index():
            return self._render_dashboard()
        
        @self.app.route('/api/metrics')
        def metrics():
            return self._get_metrics_json()
        
        @self.app.route('/api/status')
        def status():
            return self._get_status_json()
    
    def _render_dashboard(self):
        """Render the HTML dashboard."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Anomaly Detection Dashboard</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style>
                * { margin: 0; padding: 0; box-sizing: border-box; }
                body {
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
                    color: #fff;
                    min-height: 100vh;
                    padding: 20px;
                }
                .container {
                    max-width: 1200px;
                    margin: 0 auto;
                }
                h1 {
                    text-align: center;
                    margin-bottom: 30px;
                    font-size: 2.5em;
                    text-shadow: 0 2px 4px rgba(0,0,0,0.3);
                }
                .grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 20px;
                    margin-bottom: 30px;
                }
                .card {
                    background: rgba(255, 255, 255, 0.1);
                    backdrop-filter: blur(10px);
                    border: 1px solid rgba(255, 255, 255, 0.2);
                    border-radius: 10px;
                    padding: 20px;
                    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
                }
                .card h2 {
                    font-size: 0.9em;
                    opacity: 0.8;
                    margin-bottom: 10px;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                }
                .card .value {
                    font-size: 2em;
                    font-weight: bold;
                    color: #4ade80;
                }
                .card.warning .value {
                    color: #fbbf24;
                }
                .card.danger .value {
                    color: #f87171;
                }
                .metric-row {
                    display: flex;
                    justify-content: space-between;
                    margin: 8px 0;
                    font-size: 0.9em;
                }
                .metric-row .label {
                    opacity: 0.8;
                }
                .metric-row .value {
                    font-weight: bold;
                }
                .list-section {
                    background: rgba(255, 255, 255, 0.1);
                    backdrop-filter: blur(10px);
                    border: 1px solid rgba(255, 255, 255, 0.2);
                    border-radius: 10px;
                    padding: 20px;
                    margin-bottom: 20px;
                }
                .list-section h2 {
                    font-size: 1.2em;
                    margin-bottom: 15px;
                    border-bottom: 2px solid rgba(255, 255, 255, 0.2);
                    padding-bottom: 10px;
                }
                .ip-item {
                    background: rgba(0, 0, 0, 0.2);
                    padding: 10px;
                    margin: 5px 0;
                    border-radius: 5px;
                    border-left: 3px solid #f87171;
                }
                .ip-item.item:nth-child(even) {
                    background: rgba(0, 0, 0, 0.3);
                }
                .empty {
                    text-align: center;
                    opacity: 0.6;
                    padding: 20px;
                    font-style: italic;
                }
                .footer {
                    text-align: center;
                    opacity: 0.6;
                    font-size: 0.9em;
                    margin-top: 20px;
                }
                @media (max-width: 768px) {
                    h1 { font-size: 1.8em; }
                    .card .value { font-size: 1.5em; }
                }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🛡️ Anomaly Detection Dashboard</h1>
                
                <div class="grid" id="metrics-grid"></div>
                
                <div class="list-section">
                    <h2>Blocked IPs</h2>
                    <div id="blocked-ips-list"></div>
                </div>
                
                <div class="list-section">
                    <h2>Top 10 IPs by Request Rate</h2>
                    <div id="top-ips-list"></div>
                </div>
                
                <div class="footer">
                    Last updated: <span id="last-update">--:--:--</span> | 
                    Uptime: <span id="uptime">--</span>
                </div>
            </div>
            
            <script>
                const updateDashboard = async () => {
                    try {
                        const metricsResp = await fetch('/api/metrics');
                        const metrics = await metricsResp.json();
                        
                        // Update metrics grid
                        const grid = document.getElementById('metrics-grid');
                        grid.innerHTML = `
                            <div class="card ${metrics.blocked_count > 0 ? 'danger' : ''}">
                                <h2>Blocked IPs</h2>
                                <div class="value">${metrics.blocked_count}</div>
                            </div>
                            <div class="card">
                                <h2>Global Req/s</h2>
                                <div class="value">${metrics.global_rate.toFixed(2)}</div>
                            </div>
                            <div class="card">
                                <h2>Baseline Mean</h2>
                                <div class="value">${metrics.baseline_mean.toFixed(2)}</div>
                            </div>
                            <div class="card">
                                <h2>CPU Usage</h2>
                                <div class="value">${metrics.cpu_percent.toFixed(1)}%</div>
                            </div>
                            <div class="card">
                                <h2>Memory Usage</h2>
                                <div class="value">${metrics.memory_percent.toFixed(1)}%</div>
                            </div>
                            <div class="card">
                                <h2>Uptime</h2>
                                <div class="value">${metrics.uptime}</div>
                            </div>
                        `;
                        
                        // Update blocked IPs list
                        const blockedList = document.getElementById('blocked-ips-list');
                        if (metrics.blocked_ips.length === 0) {
                            blockedList.innerHTML = '<div class="empty">No IPs currently blocked</div>';
                        } else {
                            blockedList.innerHTML = metrics.blocked_ips
                                .map(ip => `<div class="ip-item">
                                    <div><strong>${ip}</strong></div>
                                    <div class="metric-row" style="font-size: 0.85em; margin-top: 5px;">
                                        <span>Rate: ${metrics.ip_rates[ip] || 'N/A'} req/s</span>
                                    </div>
                                </div>`)
                                .join('');
                        }
                        
                        // Update top IPs list
                        const topList = document.getElementById('top-ips-list');
                        if (metrics.top_ips.length === 0) {
                            topList.innerHTML = '<div class="empty">No traffic yet</div>';
                        } else {
                            topList.innerHTML = metrics.top_ips
                                .map((item, idx) => `<div class="ip-item">
                                    <div style="display: flex; justify-content: space-between;">
                                        <strong>#${idx + 1} ${item.ip}</strong>
                                        <span>${item.rate.toFixed(2)} req/s</span>
                                    </div>
                                </div>`)
                                .join('');
                        }
                        
                        // Update last update time
                        const now = new Date();
                        document.getElementById('last-update').textContent = 
                            now.toLocaleTimeString();
                        
                        document.getElementById('uptime').textContent = metrics.uptime;
                    } catch (error) {
                        console.error('Dashboard update failed:', error);
                    }
                };
                
                // Update immediately and then every 3 seconds
                updateDashboard();
                setInterval(updateDashboard, 3000);
            </script>
        </body>
        </html>
        """
        return html
    
    def _get_metrics_json(self):
        """Get metrics as JSON."""
        metrics = {
            'timestamp': datetime.now().isoformat(),
            'uptime': self._format_uptime(),
            'global_rate': self.monitor.get_global_rate() if self.monitor else 0,
            'blocked_count': len(self.blocker.get_blocked_ips()) if self.blocker else 0,
            'blocked_ips': self.blocker.get_blocked_ips() if self.blocker else [],
            'baseline_mean': self.baseline_calc.get_global_baseline()['mean'] if self.baseline_calc else 0,
            'baseline_stddev': self.baseline_calc.get_global_baseline()['stddev'] if self.baseline_calc else 0,
            'cpu_percent': psutil.cpu_percent(interval=0.1),
            'memory_percent': psutil.virtual_memory().percent,
            'top_ips': [],
            'ip_rates': {}
        }
        
        # Top 10 IPs by rate
        if self.monitor:
            ip_rates = []
            for ip in self.monitor.get_active_ips():
                rate = self.monitor.get_per_ip_rate(ip)
                metrics['ip_rates'][ip] = f"{rate:.2f}"
                ip_rates.append({'ip': ip, 'rate': rate})
            
            ip_rates.sort(key=lambda x: x['rate'], reverse=True)
            metrics['top_ips'] = ip_rates[:10]
        
        return jsonify(metrics)
    
    def _get_status_json(self):
        """Get status as JSON."""
        return jsonify({
            'status': 'ok',
            'timestamp': datetime.now().isoformat()
        })
    
    def _format_uptime(self):
        """Format uptime as human-readable string."""
        elapsed = time.time() - self.start_time
        hours = int(elapsed // 3600)
        minutes = int((elapsed % 3600) // 60)
        seconds = int(elapsed % 60)
        return f"{hours}h {minutes}m {seconds}s"
    
    def run(self, debug=False):
        """Start the Flask server."""
        logger.info("Starting dashboard on %s:%d", self.host, self.port)
        self.app.run(host=self.host, port=self.port, debug=debug, threaded=True)
