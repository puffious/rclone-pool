# Build a minimal Docker image for rclonepool
FROM python:3.11-slim

# Install rclone
RUN apt-get update && \
    apt-get install -y curl unzip && \
    curl https://rclone.org/install.sh | bash && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create application directory
WORKDIR /app

# Copy application files
COPY *.py /app/
COPY requirements.txt /app/

# Install Python dependencies (if any beyond stdlib)
RUN pip install --no-cache-dir -r requirements.txt || true

# Create necessary directories
RUN mkdir -p /config /data /tmp/rclonepool

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV RCLONE_CONFIG=/config/rclone.conf
ENV RCLONEPOOL_CONFIG=/config/config.json

# Expose WebDAV port
EXPOSE 8080

# Volume for persistent configuration
VOLUME ["/config"]

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080').read()" || exit 1

# Default command: run WebDAV server
CMD ["python", "rclonepool.py", "serve", "--config", "/config/config.json", "--host", "0.0.0.0", "--port", "8080"]
