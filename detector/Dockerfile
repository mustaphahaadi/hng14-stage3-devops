FROM python:3.11-slim

# Install system dependencies including iptables and sudo
RUN apt-get update && apt-get install -y \
    iptables \
    sudo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy detector source files
COPY main.py monitor.py baseline.py detector.py blocker.py \
     unbanner.py notifier.py dashboard.py ./

# Create log directory
RUN mkdir -p /var/log/hng-detector && chmod 777 /var/log/hng-detector

# Run as root to allow sudo access for iptables (safer than giving full sudo)
USER root

# Expose dashboard port
EXPOSE 8000

# Set entrypoint
ENTRYPOINT ["python", "main.py"]
