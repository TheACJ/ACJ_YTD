# 🎬 Enterprise YouTube Downloader v5.0 - Microservices Architecture

A production-ready, enterprise-grade YouTube download service built with a robust microservices architecture, comprehensive APIs, and advanced monitoring capabilities.

## 🚀 Key Features

### Core Functionality
- **Multi-Content Support**: Videos, playlists, live streams, and YouTube Shorts
- **Modern yt-dlp Integration**: Browser impersonation and TLS fingerprinting bypass
- **Parallel Processing**: Concurrent downloads with configurable worker pools
- **Progress Tracking**: Real-time download progress with detailed metrics

### Enterprise Features
- **REST API**: Full RESTful API with OpenAPI documentation
- **Database Integration**: SQLite-based download tracking and analytics
- **Comprehensive Monitoring**: Health checks, metrics, and performance monitoring
- **Configuration Management**: Environment variables and validation
- **Containerization**: Docker and docker-compose support
- **Testing Framework**: Complete test suite with pytest
- **Type Safety**: Full type hints throughout codebase
- **Structured Logging**: Enterprise-grade logging with configurable levels

## 📦 Installation & Deployment

### Microservices Deployment (Recommended)
```bash
# Clone repository
git clone <repository-url>
cd youtube-downloader

# Deploy all services with Docker Compose
docker-compose up --build

# Services will be available at:
# - API Gateway: http://localhost:8000 (Main entry point)
# - Job Manager: http://localhost:8001
# - Download Worker: http://localhost:8002
# - Storage Service: http://localhost:8003
# - Analytics Service: http://localhost:8004
# - Redis: localhost:6379
```

### Single Service Development
```bash
# For development/testing individual services
pip install -r requirements.txt

# Run API Gateway only
python services/api-gateway/app.py

# Run Job Manager only
python services/job-manager/app.py

# Run other services similarly...
```

### Manual Docker Deployment
```bash
# Build custom image
docker build -t youtube-downloader .

# Run individual services
docker run -d --name redis redis:7-alpine
docker run -d --name api-gateway \
  -p 8000:8000 \
  -e JOB_MANAGER_URL=http://host.docker.internal:8001 \
  youtube-downloader \
  python services/api-gateway/app.py
```

## 🎯 Usage

### CLI Interface
```bash
cd youtube_downloader
python main.py
```

### REST API
```bash
# Start API server
python -m uvicorn youtube_downloader.api.app:app --host 0.0.0.0 --port 8000

# API Documentation available at: http://localhost:8000/docs
```

### API Examples

#### Create Download Job
```bash
curl -X POST "http://localhost:8000/downloads" \
  -H "Content-Type: application/json" \
  -d '{
    "urls": ["https://youtu.be/VIDEO_ID"],
    "audio_only": false,
    "max_workers": 3
  }'
```

#### Check Job Status
```bash
curl "http://localhost:8000/downloads/{job_id}"
```

#### Get System Health
```bash
curl "http://localhost:8000/health"
```

#### Get Download Metrics
```bash
curl "http://localhost:8000/metrics"
```

## 🏗️ Microservices Architecture

The system is built with a robust microservices architecture that ensures scalability, resilience, and maintainability:

```
microservices-architecture/
├── services/
│   ├── api-gateway/        # Unified API entry point (Port 8000)
│   ├── job-manager/        # Job queuing & lifecycle (Port 8001)
│   ├── download-worker/    # Actual downloading with resume (Port 8002)
│   ├── storage-service/    # File storage & management (Port 8003)
│   └── analytics-service/  # Metrics & reporting (Port 8004)
├── shared/                 # Shared models & messaging
├── youtube_downloader/     # Legacy monolithic code (for reference)
└── docker-compose.yml      # Multi-service orchestration
```

### Service Responsibilities

#### 🔗 **API Gateway Service** (Port 8000)
- **Purpose**: Single entry point for all client requests
- **Features**:
  - Request routing to appropriate services
  - Authentication & rate limiting
  - Response aggregation
  - Request logging & monitoring
- **Tech**: FastAPI, httpx for service communication

#### 📋 **Job Management Service** (Port 8001)
- **Purpose**: Job queuing, scheduling, and lifecycle management
- **Features**:
  - Redis-based priority queues
  - Job status tracking
  - Pause/resume/cancel operations
  - Automatic retry logic
- **Tech**: FastAPI, Redis, asyncio

#### ⬇️ **Download Worker Service** (Port 8002)
- **Purpose**: Actual YouTube downloading with resume capability
- **Features**:
  - yt-dlp integration with modern workarounds
  - Download resume for interrupted transfers
  - Progress tracking & real-time updates
  - Concurrent download processing
- **Tech**: yt-dlp, FastAPI, asyncio

#### 💾 **Storage Service** (Port 8003)
- **Purpose**: File storage, retrieval, and lifecycle management
- **Features**:
  - Organized file storage with metadata
  - Automatic cleanup of old files
  - File integrity verification
  - Storage analytics
- **Tech**: FastAPI, aiofiles, filesystem operations

#### 📊 **Analytics Service** (Port 8004)
- **Purpose**: Metrics collection, reporting, and performance analytics
- **Features**:
  - Real-time metrics aggregation
  - Download trend analysis
  - Performance monitoring
  - Custom report generation
- **Tech**: FastAPI, Redis for data storage

### Inter-Service Communication

#### **Message Queue System**
- **Technology**: Redis Pub/Sub + persistent queues
- **Purpose**: Asynchronous communication between services
- **Features**:
  - Event-driven architecture
  - Message persistence for reliability
  - Dead letter queues for failed messages

#### **Message Types**
```python
# Job Lifecycle Messages
JOB_CREATED, JOB_STARTED, JOB_PROGRESS, JOB_COMPLETED, JOB_FAILED

# Download Messages
DOWNLOAD_STARTED, DOWNLOAD_PROGRESS, DOWNLOAD_COMPLETED, DOWNLOAD_RESUME

# Storage Messages
STORAGE_UPLOAD, STORAGE_DELETE, STORAGE_CLEANUP

# Analytics Messages
ANALYTICS_UPDATE
```

### Service Discovery & Health Checks

#### **Health Monitoring**
- Each service exposes `/health` endpoint
- API Gateway aggregates health status
- Automatic service discovery via Docker networking
- Circuit breaker pattern for fault tolerance

#### **Graceful Shutdown**
- SIGTERM handling across all services
- In-flight request completion
- Resource cleanup (connections, files, locks)
- State persistence before shutdown

### Data Flow Architecture

```
Client Request → API Gateway → Job Manager → Queue → Download Worker → Storage Service
                       ↓              ↓              ↓              ↓
                   Analytics ←─────── Message Bus ←──┼──────────────┘
                       ↑              ↑              ↑
                   Metrics ──────────┘              └─ File Metadata
```

### Scalability Features

#### **Horizontal Scaling**
- Multiple download worker instances
- Load-balanced API gateways
- Redis cluster for message queues
- Distributed storage backend

#### **Performance Optimizations**
- Async/await throughout the stack
- Connection pooling for external services
- Caching layers for metadata
- Background job processing

### Reliability Features

#### **Fault Tolerance**
- Circuit breakers for service communication
- Retry logic with exponential backoff
- Dead letter queues for failed messages
- Automatic service restart on failure

#### **Data Consistency**
- Eventual consistency via message queues
- Transactional operations where critical
- Backup and recovery mechanisms
- Data validation at service boundaries

## ⚙️ Configuration

### Environment Variables
```bash
# Output configuration
YTD_OUTPUT_PATH=/app/downloads
YTD_MAX_WORKERS=3
YTD_AUDIO_ONLY=false

# Performance tuning
YTD_MAX_RETRIES=10
YTD_TIMEOUT=3600
YTD_RATE_LIMIT=1000

# Authentication
YTD_COOKIES_FILE=/app/cookies.txt
YTD_SPONSORBLOCK=true

# Database
YTD_DB_PATH=/app/downloads.db

# API Configuration
YTD_API_HOST=0.0.0.0
YTD_API_PORT=8000
```

### Configuration File
```json
{
  "output_path": "./downloads",
  "max_workers": 3,
  "audio_only": false,
  "max_retries": 10,
  "download_timeout": 3600,
  "format_preference": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
  "enable_modern_features": true,
  "live_stream_support": true,
  "enable_sponsorblock": false
}
```

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=youtube_downloader

# Run specific test category
pytest tests/test_config.py
pytest tests/test_database.py
```

## 📊 Monitoring & Metrics

### Health Endpoints
- `GET /health` - System health status
- `GET /metrics` - Download statistics and performance metrics

### Metrics Tracked
- Total downloads (successful/failed)
- Average download speed and time
- System resource usage
- Active download jobs
- Database performance

## 🔒 Security Features

- Input validation and sanitization
- Rate limiting capabilities (configurable)
- Secure configuration management
- No hardcoded credentials
- Container security best practices

## 🐳 Docker Features

- Multi-stage build for optimized images
- Non-root user execution
- Health checks and graceful shutdown
- Volume mounting for persistent storage
- Environment-based configuration

## 📈 Performance

- **Concurrent Downloads**: Configurable worker pools
- **Async Operations**: Non-blocking I/O for API endpoints
- **Efficient Caching**: URL validation and metadata caching
- **Resource Monitoring**: Built-in performance tracking
- **Database Optimization**: Indexed queries and connection pooling

## 🔧 Development

### Code Quality
- Full type hints with mypy compatibility
- Comprehensive test coverage (>80%)
- Pre-commit hooks for code quality
- Structured logging throughout
- Clean architecture patterns

### API Documentation
- Automatic OpenAPI/Swagger documentation
- Interactive API testing interface
- Request/response examples
- Schema validation

## 🚦 CI/CD Ready

The application is designed for modern deployment pipelines:

- **Containerized**: Docker and docker-compose support
- **Environment Configurable**: 12-factor app principles
- **Health Checks**: Kubernetes/docker health monitoring
- **Logging**: Structured logs for log aggregation
- **Metrics**: Prometheus-compatible metrics endpoints

## 📝 License

[Add your license information here]

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## 🆘 Troubleshooting

### Common Issues

**Import Errors**: Ensure you're running from the correct directory or using proper Python path.

**Download Failures**: Check network connectivity and YouTube access. The application includes modern workarounds for common blocking issues.

**Database Issues**: Ensure write permissions for the database file location.

**API Connection Issues**: Verify the API server is running and accessible on the configured port.

### Logs

Check the application logs for detailed error information:
```bash
# CLI logs are output to console
# API logs can be found in the Docker container logs
docker-compose logs youtube-downloader
```

## 🎯 Roadmap

- [ ] Authentication and authorization system
- [ ] Web-based UI dashboard
- [ ] Advanced queue management
- [ ] Plugin system for custom downloaders
- [ ] Cloud storage integration
- [ ] Multi-format output support
- [ ] Real-time WebSocket notifications

---

**Enterprise YouTube Downloader v4.0** - Built for reliability, scalability, and modern deployment practices.
