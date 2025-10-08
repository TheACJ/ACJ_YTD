# Multi-stage build for enterprise YouTube Downloader Microservices
FROM python:3.11-slim as base

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared modules
COPY shared/ ./shared/

# Production stage
FROM base as production

# Create non-root user
RUN useradd --create-home --shell /bin/bash app \
    && mkdir -p /app/downloads /app/storage /app/resume_data \
    && chown -R app:app /app

USER app

# Copy application code
COPY --chown=app:app youtube_downloader/ ./youtube_downloader/
COPY --chown=app:app services/ ./services/

# Health check (will be overridden by service-specific checks)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; print('Container healthy')" || exit 1

# Expose port (will be overridden by service-specific ports)
EXPOSE 8000

# Default command - can be overridden by service-specific commands
CMD ["python", "-c", "print('Please specify a service to run')"]