"""Shared models and message types for microservices communication"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Union
from datetime import datetime
from enum import Enum
from pathlib import Path

class JobStatus(str, Enum):
    """Job status enumeration"""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class MessageType(str, Enum):
    """Message types for inter-service communication"""
    JOB_CREATED = "job_created"
    JOB_STARTED = "job_started"
    JOB_PROGRESS = "job_progress"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"
    JOB_CANCELLED = "job_cancelled"
    JOB_RESUME = "job_resume"
    JOB_PAUSE = "job_pause"

    DOWNLOAD_STARTED = "download_started"
    DOWNLOAD_PROGRESS = "download_progress"
    DOWNLOAD_COMPLETED = "download_completed"
    DOWNLOAD_FAILED = "download_failed"
    DOWNLOAD_RESUME = "download_resume"

    STORAGE_UPLOAD = "storage_upload"
    STORAGE_DELETE = "storage_delete"
    STORAGE_CLEANUP = "storage_cleanup"

    ANALYTICS_UPDATE = "analytics_update"
    HEALTH_CHECK = "health_check"

@dataclass
class ServiceMessage:
    """Base message structure for inter-service communication"""
    message_id: str
    message_type: MessageType
    service: str
    timestamp: datetime = field(default_factory=datetime.now)
    correlation_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)

@dataclass
class DownloadJob:
    """Download job representation"""
    id: str
    urls: List[str]
    config: Dict[str, Any]
    status: JobStatus = JobStatus.PENDING
    priority: int = 1
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    progress: float = 0.0
    error: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    resume_data: Optional[Dict[str, Any]] = None

@dataclass
class DownloadTask:
    """Individual download task within a job"""
    id: str
    job_id: str
    url: str
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    file_path: Optional[Path] = None
    file_size: Optional[int] = None
    downloaded_bytes: int = 0
    speed: Optional[float] = None
    eta: Optional[float] = None
    error: Optional[str] = None
    resume_data: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class StorageRequest:
    """Storage service request"""
    operation: str  # upload, download, delete, cleanup
    file_path: Optional[Path] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    job_id: Optional[str] = None
    task_id: Optional[str] = None

@dataclass
class AnalyticsEvent:
    """Analytics event for metrics collection"""
    event_type: str
    service: str
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    user_id: Optional[str] = None
    session_id: Optional[str] = None

@dataclass
class HealthStatus:
    """Service health status"""
    service: str
    status: str  # healthy, degraded, unhealthy
    timestamp: datetime = field(default_factory=datetime.now)
    version: str = "1.0.0"
    uptime: Optional[float] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    dependencies: Dict[str, str] = field(default_factory=dict)

@dataclass
class ResumeData:
    """Data needed to resume a download"""
    url: str
    file_path: Path
    downloaded_bytes: int
    total_bytes: Optional[int] = None
    last_modified: Optional[datetime] = None
    etag: Optional[str] = None
    yt_dlp_state: Optional[Dict[str, Any]] = None

# Message factory functions
def create_job_message(job_id: str, message_type: MessageType, payload: Dict[str, Any]) -> ServiceMessage:
    """Create a job-related message"""
    return ServiceMessage(
        message_id=f"{job_id}_{message_type.value}_{datetime.now().isoformat()}",
        message_type=message_type,
        service="job-manager",
        payload={"job_id": job_id, **payload}
    )

def create_download_message(task_id: str, message_type: MessageType, payload: Dict[str, Any]) -> ServiceMessage:
    """Create a download-related message"""
    return ServiceMessage(
        message_id=f"{task_id}_{message_type.value}_{datetime.now().isoformat()}",
        message_type=message_type,
        service="download-worker",
        payload={"task_id": task_id, **payload}
    )

def create_storage_message(operation: str, payload: Dict[str, Any]) -> ServiceMessage:
    """Create a storage-related message"""
    return ServiceMessage(
        message_id=f"storage_{operation}_{datetime.now().isoformat()}",
        message_type=MessageType.STORAGE_UPLOAD,
        service="storage-service",
        payload={"operation": operation, **payload}
    )

def create_analytics_message(event_type: str, data: Dict[str, Any]) -> ServiceMessage:
    """Create an analytics message"""
    return ServiceMessage(
        message_id=f"analytics_{event_type}_{datetime.now().isoformat()}",
        message_type=MessageType.ANALYTICS_UPDATE,
        service="analytics-service",
        payload={"event_type": event_type, "data": data}
    )