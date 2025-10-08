"""Enterprise-grade REST API for YouTube Downloader"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime
import asyncio
from pathlib import Path
import sys
import os

# Added project root to path for proper imports
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from youtube_downloader.models.data_models import (
    DownloadJob, DownloadResult, DownloadConfig, DownloadMetrics,
    SystemHealth, VideoInfo, PlaylistInfo
)
from pydantic import BaseModel

class DownloadRequest(BaseModel):
    """Request model for download jobs"""
    urls: List[str]
    audio_only: bool = False
    output_path: Optional[str] = None
    max_workers: Optional[int] = None
from youtube_downloader.models.database import DatabaseManager
from youtube_downloader.config.config_manager import ConfigManager
from youtube_downloader.core.downloader import YouTubeDownloader
from youtube_downloader.core.url_handler import validate_youtube_url, get_content_type
from youtube_downloader.utils.logger import setup_logger

# Initialize components
logger = setup_logger(__name__)
db = DatabaseManager()
config = ConfigManager()

# Global job tracker
active_jobs: Dict[str, DownloadJob] = {}

app = FastAPI(
    title=" The ACJ's sYouTube Downloader API",
    description="Enterprise-grade YouTube download service with REST API",
    version="4.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Initialize application on startup"""
    logger.info("Starting YouTube Downloader API v4.0.0")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("Shutting down YouTube Downloader API")

async def get_db() -> DatabaseManager:
    """Dependency for database access"""
    return db

async def get_config() -> ConfigManager:
    """Dependency for configuration access"""
    return config

@app.get("/health", response_model=SystemHealth)
async def health_check(db: DatabaseManager = Depends(get_db)):
    """Health check endpoint"""
    try:
        # Check database connectivity
        metrics = db.get_metrics()

        # Get system info
        import psutil
        disk_usage = psutil.disk_usage('/')

        return SystemHealth(
            status="healthy",
            uptime=0.0,  # Would need to track actual uptime
            active_downloads=len(active_jobs),
            total_downloads=metrics.total_downloads,
            disk_usage={
                "total": disk_usage.total,
                "used": disk_usage.used,
                "free": disk_usage.free,
                "percent": disk_usage.percent
            }
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service unhealthy")

@app.get("/metrics", response_model=DownloadMetrics)
async def get_metrics(db: DatabaseManager = Depends(get_db)):
    """Get download metrics"""
    return db.get_metrics()

@app.post("/downloads", response_model=Dict[str, str])
async def create_download_job(
    request: DownloadRequest,
    background_tasks: BackgroundTasks,
    db: DatabaseManager = Depends(get_db),
    config: ConfigManager = Depends(get_config)
):
    """Create a new download job"""
    # Validate URLs
    valid_urls = []
    for url in request.urls:
        if validate_youtube_url(url):
            valid_urls.append(url)
        else:
            raise HTTPException(status_code=400, detail=f"Invalid YouTube URL: {url}")

    if not valid_urls:
        raise HTTPException(status_code=400, detail="No valid YouTube URLs provided")

    # Create job configuration
    job_config = DownloadConfig(
        output_path=Path(request.output_path or config.get('output_path')),
        audio_only=request.audio_only,
        max_workers=request.max_workers or config.get('max_workers', 3)
    )

    # Create job
    job_id = str(uuid.uuid4())
    job = DownloadJob(
        id=job_id,
        urls=valid_urls,
        config=job_config,
        status="pending"
    )

    # Save to database
    db.save_download_job(job)
    active_jobs[job_id] = job

    # Start background download
    background_tasks.add_task(process_download_job, job_id)

    return {"job_id": job_id, "status": "accepted", "message": "Download job created"}

async def process_download_job(job_id: str):
    """Process a download job in the background"""
    try:
        job = active_jobs.get(job_id)
        if not job:
            logger.error(f"Job {job_id} not found in active jobs")
            return

        # Update job status
        job.status = "running"
        job.started_at = datetime.now()
        db.save_download_job(job)

        # Create a temporary config manager from job config
        temp_config = ConfigManager()
        temp_config.config.update({
            'output_path': str(job.config.output_path),
            'audio_only': job.config.audio_only,
            'max_workers': job.config.max_workers,
            'format_preference': job.config.format_preference,
            'enable_sponsorblock': getattr(job.config, 'enable_sponsorblock', False),
        })

        # Initialize downloader
        downloader = YouTubeDownloader(temp_config)

        # Process downloads
        results = await asyncio.get_event_loop().run_in_executor(
            None, downloader.download_multiple_urls, job.urls, job.config.audio_only
        )

        # Save results
        for result in results:
            db.save_download_result(job_id, result)

        # Update metrics
        db.update_metrics(results)

        # Update job status
        job.status = "completed"
        job.completed_at = datetime.now()
        job.results = results
        db.save_download_job(job)

        logger.info(f"Job {job_id} completed successfully")

    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        job = active_jobs.get(job_id)
        if job:
            job.status = "failed"
            job.error = str(e)
            job.completed_at = datetime.now()
            db.save_download_job(job)
    finally:
        # Clean up active jobs
        active_jobs.pop(job_id, None)

@app.get("/downloads/{job_id}", response_model=DownloadJob)
async def get_download_job(job_id: str, db: DatabaseManager = Depends(get_db)):
    """Get download job status and results"""
    # Check active jobs first
    if job_id in active_jobs:
        job = active_jobs[job_id]
        # Load latest results from database
        job.results = db.get_download_results(job_id)
        return job

    # Check database
    job = db.get_download_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Load results
    job.results = db.get_download_results(job_id)
    return job

@app.get("/downloads/{job_id}/results", response_model=List[DownloadResult])
async def get_download_results(job_id: str, db: DatabaseManager = Depends(get_db)):
    """Get download results for a job"""
    results = db.get_download_results(job_id)
    if not results:
        # Check if job exists
        job = db.get_download_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
    return results

@app.get("/downloads")
async def list_download_jobs(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, description="Maximum number of jobs to return"),
    offset: int = Query(0, description="Number of jobs to skip"),
    db: DatabaseManager = Depends(get_db)
):
    """List download jobs with optional filtering"""
    # This is a simplified implementation
    # In production, you'd want proper pagination and filtering
    with db._get_connection() as conn:
        query = "SELECT id, status, created_at FROM download_jobs"
        params = []

        if status:
            query += " WHERE status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()

        jobs = []
        for row in rows:
            job = db.get_download_job(row['id'])
            if job:
                jobs.append(job)

        return {"jobs": jobs, "total": len(jobs)}

@app.delete("/downloads/{job_id}")
async def cancel_download_job(job_id: str):
    """Cancel a running download job"""
    if job_id in active_jobs:
        job = active_jobs[job_id]
        job.status = "cancelled"
        job.completed_at = datetime.now()
        job.error = "Cancelled by user"
        db.save_download_job(job)
        active_jobs.pop(job_id, None)
        return {"message": "Job cancelled"}
    else:
        raise HTTPException(status_code=404, detail="Job not found or not running")

@app.post("/validate-url")
async def validate_url(url: str):
    """Validate a YouTube URL"""
    is_valid = validate_youtube_url(url)
    if is_valid:
        content_type = get_content_type(url)
        return {
            "valid": True,
            "content_type": content_type,
            "url": url
        }
    else:
        return {
            "valid": False,
            "error": "Invalid YouTube URL",
            "url": url
        }

@app.get("/config")
async def get_configuration(config: ConfigManager = Depends(get_config)):
    """Get current configuration"""
    return config.get_all_config()

@app.put("/config")
async def update_configuration(
    updates: Dict[str, Any],
    config: ConfigManager = Depends(get_config)
):
    """Update configuration"""
    for key, value in updates.items():
        config.set(key, value)
    config.save_config()
    return {"message": "Configuration updated"}

@app.post("/maintenance/cleanup")
async def cleanup_old_jobs(days: int = 30, db: DatabaseManager = Depends(get_db)):
    """Clean up old download jobs and results"""
    deleted_count = db.cleanup_old_jobs(days)
    return {"message": f"Cleaned up {deleted_count} old jobs"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)