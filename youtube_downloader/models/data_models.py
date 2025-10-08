from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Union
from datetime import datetime
from pathlib import Path

@dataclass
class DownloadResult:
    """Result of a download operation"""
    success: bool
    url: str
    title: Optional[str] = None
    duration: Optional[int] = None
    error: Optional[str] = None
    file_path: Optional[Path] = None
    content_type: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    timestamp: Optional[datetime] = None
    file_size: Optional[int] = None
    download_time: Optional[float] = None

    def __post_init__(self) -> None:
        if self.timestamp is None:
            self.timestamp = datetime.now()

@dataclass
class PlaylistInfo:
    """Information about a playlist"""
    url: str
    title: str
    entry_count: int
    entries: Optional[List[Dict[str, Any]]] = None
    uploader: Optional[str] = None
    description: Optional[str] = None

@dataclass
class VideoInfo:
    """Information about a video"""
    url: str
    title: str
    duration: int
    uploader: Optional[str] = None
    view_count: Optional[int] = None
    upload_date: Optional[str] = None
    thumbnail: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None

@dataclass
class DownloadConfig:
    """Configuration for downloads"""
    output_path: Path
    audio_only: bool = False
    format_preference: str = 'best'
    max_workers: int = 3
    enable_progress: bool = True
    cookies_file: Optional[Path] = None
    max_retries: int = 10
    timeout: int = 3600
    rate_limit: Optional[int] = None

@dataclass
class DownloadJob:
    """Represents a download job"""
    id: str
    urls: List[str]
    config: DownloadConfig
    status: str = "pending"  # pending, running, completed, failed
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    results: List[DownloadResult] = field(default_factory=list)
    error: Optional[str] = None

@dataclass
class SystemHealth:
    """System health status"""
    status: str  # healthy, degraded, unhealthy
    timestamp: datetime = field(default_factory=datetime.now)
    version: str = "4.0.0"
    uptime: Optional[float] = None
    active_downloads: int = 0
    total_downloads: int = 0
    disk_usage: Optional[Dict[str, Any]] = None

@dataclass
class DownloadMetrics:
    """Download performance metrics"""
    total_downloads: int = 0
    successful_downloads: int = 0
    failed_downloads: int = 0
    total_bytes_downloaded: int = 0
    average_download_speed: float = 0.0
    average_download_time: float = 0.0
    last_updated: datetime = field(default_factory=datetime.now)