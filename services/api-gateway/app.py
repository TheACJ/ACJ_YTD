"""API Gateway Service - Unified interface for all microservices"""

import asyncio
import os
import httpx
from typing import Dict, List, Optional, Any
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
import uvicorn

# Import shared modules
import sys
sys.path.append('/app')
from shared.models import HealthStatus

class ServiceRegistry:
    """Service registry for microservice discovery"""

    def __init__(self):
        self.services = {
            "job-manager": os.getenv("JOB_MANAGER_URL", "http://job-manager:8001"),
            "download-worker": os.getenv("DOWNLOAD_WORKER_URL", "http://download-worker:8002"),
            "storage-service": os.getenv("STORAGE_SERVICE_URL", "http://storage-service:8003"),
            "analytics-service": os.getenv("ANALYTICS_SERVICE_URL", "http://analytics-service:8004"),
        }
        self.client = httpx.AsyncClient(timeout=30.0)

    async def health_check_all(self) -> Dict[str, HealthStatus]:
        """Check health of all services"""
        health_status = {}

        for service_name, service_url in self.services.items():
            try:
                response = await self.client.get(f"{service_url}/health")
                if response.status_code == 200:
                    data = response.json()
                    health_status[service_name] = HealthStatus(
                        service=service_name,
                        status=data.get("status", "unknown"),
                        uptime=data.get("uptime"),
                        metrics=data.get("metrics", {}),
                        dependencies=data.get("dependencies", {})
                    )
                else:
                    health_status[service_name] = HealthStatus(
                        service=service_name,
                        status="unhealthy"
                    )
            except Exception as e:
                health_status[service_name] = HealthStatus(
                    service=service_name,
                    status="unreachable",
                    metrics={"error": str(e)}
                )

        return health_status

    async def call_service(self, service_name: str, method: str, path: str,
                          **kwargs) -> httpx.Response:
        """Call a service endpoint"""
        if service_name not in self.services:
            raise HTTPException(status_code=404, detail=f"Service {service_name} not found")

        service_url = self.services[service_name]
        url = f"{service_url}{path}"

        try:
            response = await self.client.request(method, url, **kwargs)
            return response
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"Service {service_name} unavailable: {str(e)}")

# Global service registry
service_registry = ServiceRegistry()

# FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    yield
    # Cleanup
    await service_registry.client.aclose()

app = FastAPI(
    title="YouTube Downloader API Gateway",
    description="Unified API interface for the microservices architecture",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests"""
    start_time = datetime.now()

    # Get client info
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")

    print(f"[{start_time.isoformat()}] {request.method} {request.url.path} - {client_ip} - {user_agent}")

    response = await call_next(request)

    process_time = (datetime.now() - start_time).total_seconds()
    print(f"[{datetime.now().isoformat()}] Completed in {process_time:.3f}s - Status: {response.status_code}")

    return response

# Download Jobs API
@app.post("/downloads", response_model=Dict[str, str])
async def create_download(
    urls: List[str],
    audio_only: bool = False,
    priority: int = Query(1, ge=1, le=10),
    background_tasks: BackgroundTasks = None
):
    """Create a new download job"""
    if not urls:
        raise HTTPException(status_code=400, detail="URLs are required")

    # Validate URLs (basic check)
    for url in urls:
        if not url.startswith(('http://', 'https://')):
            raise HTTPException(status_code=400, detail=f"Invalid URL: {url}")

    config = {
        "audio_only": audio_only,
        "max_retries": 3,
        "output_template": "/app/downloads/%(title)s.%(ext)s"
    }

    # Call job manager service
    response = await service_registry.call_service(
        "job-manager", "POST", "/jobs",
        json={"urls": urls, "config": config, "priority": priority}
    )

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    return response.json()

@app.get("/downloads/{job_id}")
async def get_download_status(job_id: str):
    """Get download job status"""
    response = await service_registry.call_service(
        "job-manager", "GET", f"/jobs/{job_id}"
    )

    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Job not found")

    return response.json()

@app.delete("/downloads/{job_id}")
async def cancel_download(job_id: str):
    """Cancel a download job"""
    response = await service_registry.call_service(
        "job-manager", "DELETE", f"/jobs/{job_id}"
    )

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    return response.json()

@app.post("/downloads/{job_id}/pause")
async def pause_download(job_id: str):
    """Pause a download job"""
    response = await service_registry.call_service(
        "job-manager", "POST", f"/jobs/{job_id}/pause"
    )

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    return response.json()

@app.post("/downloads/{job_id}/resume")
async def resume_download(job_id: str):
    """Resume a paused download job"""
    response = await service_registry.call_service(
        "job-manager", "POST", f"/jobs/{job_id}/resume"
    )

    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.text)

    return response.json()

# System Status API
@app.get("/health")
async def system_health():
    """Get overall system health"""
    service_health = await service_registry.health_check_all()

    # Determine overall system health
    unhealthy_services = [s for s, h in service_health.items() if h.status != "healthy"]

    overall_status = "healthy" if not unhealthy_services else "degraded"
    if len(unhealthy_services) == len(service_health):
        overall_status = "unhealthy"

    return {
        "status": overall_status,
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
        "services": {name: health.__dict__ for name, health in service_health.items()},
        "unhealthy_services": unhealthy_services
    }

@app.get("/status")
async def system_status():
    """Get detailed system status"""
    # Get job queue status
    try:
        job_response = await service_registry.call_service("job-manager", "GET", "/queue/status")
        job_status = job_response.json() if job_response.status_code == 200 else {}
    except:
        job_status = {"error": "Job manager unavailable"}

    # Get worker status
    try:
        worker_response = await service_registry.call_service("download-worker", "GET", "/active-downloads")
        worker_status = worker_response.json() if worker_response.status_code == 200 else {}
    except:
        worker_status = {"error": "Download worker unavailable"}

    # Get analytics
    try:
        analytics_response = await service_registry.call_service("analytics-service", "GET", "/metrics")
        analytics = analytics_response.json() if analytics_response.status_code == 200 else {}
    except:
        analytics = {"error": "Analytics service unavailable"}

    return {
        "timestamp": datetime.now().isoformat(),
        "job_queue": job_status,
        "active_downloads": worker_status,
        "analytics": analytics
    }

# File Management API
@app.get("/files")
async def list_files(path: str = Query("/", description="Directory path")):
    """List files in storage"""
    try:
        response = await service_registry.call_service(
            "storage-service", "GET", "/files",
            params={"path": path}
        )
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Storage service unavailable: {str(e)}")

@app.get("/files/download")
async def download_file(filename: str):
    """Download a file"""
    try:
        response = await service_registry.call_service(
            "storage-service", "GET", f"/files/download",
            params={"filename": filename}
        )

        if response.status_code == 200:
            # Stream the file content
            return StreamingResponse(
                response.aiter_bytes(),
                media_type=response.headers.get("content-type", "application/octet-stream"),
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        else:
            raise HTTPException(status_code=response.status_code, detail="File not found")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Storage service unavailable: {str(e)}")

@app.delete("/files/{filename}")
async def delete_file(filename: str):
    """Delete a file"""
    try:
        response = await service_registry.call_service(
            "storage-service", "DELETE", f"/files/{filename}"
        )

        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail=response.text)

        return response.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Storage service unavailable: {str(e)}")

# Analytics API
@app.get("/analytics/metrics")
async def get_analytics_metrics():
    """Get analytics metrics"""
    try:
        response = await service_registry.call_service("analytics-service", "GET", "/metrics")
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Analytics service unavailable: {str(e)}")

@app.get("/analytics/reports/downloads")
async def get_download_reports(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(100, le=1000)
):
    """Get download reports"""
    params = {"limit": limit}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date

    try:
        response = await service_registry.call_service(
            "analytics-service", "GET", "/reports/downloads",
            params=params
        )
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Analytics service unavailable: {str(e)}")

# URL Validation API
@app.post("/validate-url")
async def validate_url(url: str):
    """Validate a YouTube URL"""
    # Basic validation (could be enhanced)
    if not url or not url.startswith(('http://', 'https://')):
        return {"valid": False, "error": "Invalid URL format"}

    # Could call a validation service here
    return {"valid": True, "url": url}

# Service Discovery API (for debugging)
@app.get("/services")
async def list_services():
    """List all registered services"""
    health_status = await service_registry.health_check_all()
    return {
        "services": service_registry.services,
        "health": {name: health.__dict__ for name, health in health_status.items()}
    }

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=False
    )