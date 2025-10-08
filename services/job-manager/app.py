"""Job Management Service - Handles job queuing, scheduling, and lifecycle management"""

import asyncio
import signal
import json
import os
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Import shared modules
import sys
sys.path.append('/app')
from shared.models import (
    DownloadJob, DownloadTask, JobStatus, MessageType,
    ServiceMessage, create_job_message
)
from shared.messaging import MessageBus

class JobManager:
    """Job management service with Redis-backed queue"""

    def __init__(self, redis_url: str = "redis://redis:6379"):
        self.redis_url = redis_url
        self.redis: Optional[redis.Redis] = None
        self.message_bus = MessageBus(redis_url)
        self.active_jobs: Dict[str, DownloadJob] = {}
        self._shutdown = False

    async def connect(self) -> None:
        """Connect to Redis and message bus"""
        self.redis = redis.from_url(self.redis_url)
        await self.redis.ping()
        await self.message_bus.start()

        # Subscribe to relevant messages
        await self.message_bus.subscribe(MessageType.JOB_STARTED, self._handle_job_started)
        await self.message_bus.subscribe(MessageType.JOB_COMPLETED, self._handle_job_completed)
        await self.message_bus.subscribe(MessageType.JOB_FAILED, self._handle_job_failed)
        await self.message_bus.subscribe(MessageType.JOB_PROGRESS, self._handle_job_progress)

    async def disconnect(self) -> None:
        """Disconnect from services"""
        await self.message_bus.stop()
        if self.redis:
            await self.redis.close()

    async def create_job(self, urls: List[str], config: Dict[str, Any], priority: int = 1) -> str:
        """Create a new download job"""
        job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{hash(str(urls)) % 10000}"

        job = DownloadJob(
            id=job_id,
            urls=urls,
            config=config,
            priority=priority,
            status=JobStatus.PENDING
        )

        # Store job in Redis
        await self._store_job(job)

        # Queue job for processing
        await self._queue_job(job)

        # Publish job created message
        message = create_job_message(job_id, MessageType.JOB_CREATED, {
            "urls": urls,
            "config": config,
            "priority": priority
        })
        await self.message_bus.publish(message)

        return job_id

    async def get_job(self, job_id: str) -> Optional[DownloadJob]:
        """Get job by ID"""
        # Check active jobs first
        if job_id in self.active_jobs:
            return self.active_jobs[job_id]

        # Check Redis
        return await self._load_job(job_id)

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a job"""
        job = await self.get_job(job_id)
        if not job or job.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
            return False

        job.status = JobStatus.CANCELLED
        job.completed_at = datetime.now()

        await self._store_job(job)
        await self._remove_from_queue(job_id)

        # Publish cancellation message
        message = create_job_message(job_id, MessageType.JOB_CANCELLED, {})
        await self.message_bus.publish(message)

        return True

    async def pause_job(self, job_id: str) -> bool:
        """Pause a job"""
        job = await self.get_job(job_id)
        if not job or job.status != JobStatus.RUNNING:
            return False

        job.status = JobStatus.PAUSED
        await self._store_job(job)

        message = create_job_message(job_id, MessageType.JOB_PAUSE, {})
        await self.message_bus.publish(message)

        return True

    async def resume_job(self, job_id: str) -> bool:
        """Resume a paused job"""
        job = await self.get_job(job_id)
        if not job or job.status != JobStatus.PAUSED:
            return False

        job.status = JobStatus.QUEUED
        await self._store_job(job)
        await self._queue_job(job)

        message = create_job_message(job_id, MessageType.JOB_RESUME, {})
        await self.message_bus.publish(message)

        return True

    async def get_job_queue_length(self) -> int:
        """Get the length of the job queue"""
        if not self.redis:
            return 0
        return await self.redis.llen("job_queue")

    async def get_active_jobs_count(self) -> int:
        """Get count of active jobs"""
        return len(self.active_jobs)

    async def _store_job(self, job: DownloadJob) -> None:
        """Store job in Redis"""
        if not self.redis:
            return

        job_data = {
            "id": job.id,
            "urls": job.urls,
            "config": job.config,
            "status": job.status.value,
            "priority": job.priority,
            "created_at": job.created_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "progress": job.progress,
            "error": job.error,
            "retry_count": job.retry_count,
            "max_retries": job.max_retries,
            "resume_data": job.resume_data
        }

        await self.redis.setex(
            f"job:{job.id}",
            86400 * 7,  # 7 days TTL
            json.dumps(job_data)
        )

    async def _load_job(self, job_id: str) -> Optional[DownloadJob]:
        """Load job from Redis"""
        if not self.redis:
            return None

        job_data = await self.redis.get(f"job:{job_id}")
        if not job_data:
            return None

        try:
            data = json.loads(job_data)
            return DownloadJob(
                id=data["id"],
                urls=data["urls"],
                config=data["config"],
                status=JobStatus(data["status"]),
                priority=data["priority"],
                created_at=datetime.fromisoformat(data["created_at"]),
                started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
                completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
                progress=data["progress"],
                error=data["error"],
                retry_count=data["retry_count"],
                max_retries=data["max_retries"],
                resume_data=data["resume_data"]
            )
        except Exception:
            return None

    async def _queue_job(self, job: DownloadJob) -> None:
        """Add job to processing queue"""
        if not self.redis:
            return

        # Use priority queue (sorted set with priority as score)
        await self.redis.zadd("job_queue", {job.id: job.priority})

    async def _remove_from_queue(self, job_id: str) -> None:
        """Remove job from processing queue"""
        if not self.redis:
            return

        await self.redis.zrem("job_queue", job_id)

    async def _handle_job_started(self, message: ServiceMessage) -> None:
        """Handle job started message"""
        job_id = message.payload.get("job_id")
        if job_id:
            job = await self.get_job(job_id)
            if job:
                job.status = JobStatus.RUNNING
                job.started_at = datetime.now()
                await self._store_job(job)
                self.active_jobs[job_id] = job

    async def _handle_job_completed(self, message: ServiceMessage) -> None:
        """Handle job completed message"""
        job_id = message.payload.get("job_id")
        if job_id and job_id in self.active_jobs:
            job = self.active_jobs[job_id]
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now()
            job.progress = 100.0
            await self._store_job(job)
            del self.active_jobs[job_id]

    async def _handle_job_failed(self, message: ServiceMessage) -> None:
        """Handle job failed message"""
        job_id = message.payload.get("job_id")
        error = message.payload.get("error")

        if job_id:
            job = await self.get_job(job_id)
            if job:
                job.error = error
                job.retry_count += 1

                if job.retry_count < job.max_retries:
                    # Re-queue for retry
                    job.status = JobStatus.QUEUED
                    await self._queue_job(job)
                else:
                    job.status = JobStatus.FAILED
                    job.completed_at = datetime.now()

                await self._store_job(job)

                if job_id in self.active_jobs:
                    del self.active_jobs[job_id]

    async def _handle_job_progress(self, message: ServiceMessage) -> None:
        """Handle job progress message"""
        job_id = message.payload.get("job_id")
        progress = message.payload.get("progress", 0.0)

        if job_id and job_id in self.active_jobs:
            self.active_jobs[job_id].progress = progress
            await self._store_job(self.active_jobs[job_id])

# Global job manager instance
job_manager = JobManager()

# FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    await job_manager.connect()

    # Start message consumption
    consume_task = asyncio.create_task(job_manager.message_bus.start_consuming())

    yield

    # Graceful shutdown
    job_manager._shutdown = True
    consume_task.cancel()
    try:
        await consume_task
    except asyncio.CancelledError:
        pass

    await job_manager.disconnect()

app = FastAPI(
    title="Job Management Service",
    description="Manages download jobs and queuing",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/jobs", response_model=Dict[str, str])
async def create_job(
    urls: List[str],
    config: Dict[str, Any] = None,
    priority: int = 1,
    background_tasks: BackgroundTasks = None
):
    """Create a new download job"""
    if not urls:
        raise HTTPException(status_code=400, detail="URLs are required")

    if config is None:
        config = {}

    job_id = await job_manager.create_job(urls, config, priority)
    return {"job_id": job_id, "status": "created"}

@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """Get job details"""
    job = await job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "id": job.id,
        "urls": job.urls,
        "status": job.status.value,
        "progress": job.progress,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "error": job.error,
        "retry_count": job.retry_count
    }

@app.delete("/jobs/{job_id}")
async def cancel_job(job_id: str):
    """Cancel a job"""
    success = await job_manager.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Job cannot be cancelled")

    return {"message": "Job cancelled"}

@app.post("/jobs/{job_id}/pause")
async def pause_job(job_id: str):
    """Pause a job"""
    success = await job_manager.pause_job(job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Job cannot be paused")

    return {"message": "Job paused"}

@app.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str):
    """Resume a paused job"""
    success = await job_manager.resume_job(job_id)
    if not success:
        raise HTTPException(status_code=400, detail="Job cannot be resumed")

    return {"message": "Job resumed"}

@app.get("/queue/status")
async def get_queue_status():
    """Get queue status"""
    queue_length = await job_manager.get_job_queue_length()
    active_jobs = job_manager.get_active_jobs_count()

    return {
        "queue_length": queue_length,
        "active_jobs": active_jobs,
        "total_jobs": queue_length + active_jobs
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Check Redis connectivity
        if job_manager.redis:
            await job_manager.redis.ping()

        return {
            "status": "healthy",
            "service": "job-manager",
            "timestamp": datetime.now().isoformat(),
            "active_jobs": len(job_manager.active_jobs)
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "service": "job-manager",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8001)),
        reload=False
    )