"""Download Worker Service - Handles actual downloading with resume functionality"""

import asyncio
import signal
import os
import json
from typing import Dict, List, Optional, Any
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path
import yt_dlp
from fastapi import FastAPI
import uvicorn

# Import shared modules
import sys
sys.path.append('/app')
from shared.models import (
    DownloadJob, DownloadTask, JobStatus, MessageType,
    ServiceMessage, ResumeData, create_job_message, create_download_message
)
from shared.messaging import MessageBus

class DownloadWorker:
    """Download worker with resume functionality"""

    def __init__(self, redis_url: str = "redis://redis:6379", worker_id: str = None):
        self.redis_url = redis_url
        self.worker_id = worker_id or f"worker_{os.getpid()}"
        self.message_bus = MessageBus(redis_url)
        self.active_downloads: Dict[str, DownloadTask] = {}
        self.resume_data: Dict[str, ResumeData] = {}
        self._shutdown = False

        # Create downloads directory
        self.download_dir = Path("/app/downloads")
        self.download_dir.mkdir(exist_ok=True)

    async def connect(self) -> None:
        """Connect to message bus"""
        await self.message_bus.start()

        # Subscribe to relevant messages
        await self.message_bus.subscribe(MessageType.JOB_CREATED, self._handle_job_created)
        await self.message_bus.subscribe(MessageType.JOB_PAUSE, self._handle_job_pause)
        await self.message_bus.subscribe(MessageType.JOB_RESUME, self._handle_job_resume)
        await self.message_bus.subscribe(MessageType.JOB_CANCELLED, self._handle_job_cancelled)

    async def disconnect(self) -> None:
        """Disconnect from services"""
        self._shutdown = True
        await self.message_bus.stop()

    async def _handle_job_created(self, message: ServiceMessage) -> None:
        """Handle new job creation"""
        job_id = message.payload.get("job_id")
        urls = message.payload.get("urls", [])
        config = message.payload.get("config", {})

        if job_id and urls:
            # Create download tasks for each URL
            tasks = []
            for i, url in enumerate(urls):
                task_id = f"{job_id}_task_{i}"
                task = DownloadTask(
                    id=task_id,
                    job_id=job_id,
                    url=url,
                    status=JobStatus.QUEUED
                )
                tasks.append(task)

            # Start processing tasks
            asyncio.create_task(self._process_job(job_id, tasks, config))

    async def _handle_job_pause(self, message: ServiceMessage) -> None:
        """Handle job pause"""
        job_id = message.payload.get("job_id")
        if job_id:
            # Pause all tasks for this job
            for task_id, task in self.active_downloads.items():
                if task.job_id == job_id:
                    task.status = JobStatus.PAUSED
                    # Save resume data
                    await self._save_resume_data(task)

    async def _handle_job_resume(self, message: ServiceMessage) -> None:
        """Handle job resume"""
        job_id = message.payload.get("job_id")
        if job_id:
            # Resume all tasks for this job
            for task_id, task in self.active_downloads.items():
                if task.job_id == job_id and task.status == JobStatus.PAUSED:
                    task.status = JobStatus.RUNNING
                    # Load resume data and continue
                    resume_data = await self._load_resume_data(task_id)
                    if resume_data:
                        asyncio.create_task(self._resume_download(task, resume_data))

    async def _handle_job_cancelled(self, message: ServiceMessage) -> None:
        """Handle job cancellation"""
        job_id = message.payload.get("job_id")
        if job_id:
            # Cancel all tasks for this job
            tasks_to_remove = []
            for task_id, task in self.active_downloads.items():
                if task.job_id == job_id:
                    task.status = JobStatus.CANCELLED
                    tasks_to_remove.append(task_id)

            for task_id in tasks_to_remove:
                del self.active_downloads[task_id]

    async def _process_job(self, job_id: str, tasks: List[DownloadTask], config: Dict[str, Any]) -> None:
        """Process a job with multiple tasks"""
        try:
            # Publish job started
            await self.message_bus.publish(
                create_job_message(job_id, MessageType.JOB_STARTED, {})
            )

            completed_tasks = 0
            total_tasks = len(tasks)

            for task in tasks:
                if self._shutdown:
                    break

                self.active_downloads[task.id] = task
                task.status = JobStatus.RUNNING

                try:
                    # Check for resume data
                    resume_data = await self._load_resume_data(task.id)
                    if resume_data:
                        await self._resume_download(task, resume_data)
                    else:
                        await self._download_task(task, config)

                    if task.status == JobStatus.COMPLETED:
                        completed_tasks += 1

                        # Update progress
                        progress = (completed_tasks / total_tasks) * 100
                        await self.message_bus.publish(
                            create_job_message(job_id, MessageType.JOB_PROGRESS,
                                             {"progress": progress})
                        )

                except Exception as e:
                    task.status = JobStatus.FAILED
                    task.error = str(e)

                    # Publish download failed
                    await self.message_bus.publish(
                        create_download_message(task.id, MessageType.DOWNLOAD_FAILED,
                                              {"error": str(e)})
                    )

                finally:
                    if task.id in self.active_downloads:
                        del self.active_downloads[task.id]

            # Determine job status
            if completed_tasks == total_tasks:
                await self.message_bus.publish(
                    create_job_message(job_id, MessageType.JOB_COMPLETED, {})
                )
            else:
                await self.message_bus.publish(
                    create_job_message(job_id, MessageType.JOB_FAILED,
                                     {"error": f"Completed {completed_tasks}/{total_tasks} tasks"})
                )

        except Exception as e:
            await self.message_bus.publish(
                create_job_message(job_id, MessageType.JOB_FAILED, {"error": str(e)})
            )

    async def _download_task(self, task: DownloadTask, config: Dict[str, Any]) -> None:
        """Download a single task"""
        try:
            # Publish download started
            await self.message_bus.publish(
                create_download_message(task.id, MessageType.DOWNLOAD_STARTED, {})
            )

            # Configure yt-dlp options
            ydl_opts = self._get_ydl_opts(config, task)

            # Create progress hook
            progress_data = {}
            def progress_hook(d):
                if d['status'] == 'downloading':
                    downloaded = d.get('downloaded_bytes', 0)
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    if total > 0:
                        progress = (downloaded / total) * 100
                        task.progress = progress
                        progress_data.update(d)

                        # Publish progress
                        asyncio.create_task(self.message_bus.publish(
                            create_download_message(task.id, MessageType.DOWNLOAD_PROGRESS, {
                                "progress": progress,
                                "speed": d.get("speed"),
                                "eta": d.get("eta")
                            })
                        ))

            ydl_opts['progress_hooks'] = [progress_hook]

            # Download with yt-dlp
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(task.url, download=True)

                # Update task with results
                task.status = JobStatus.COMPLETED
                task.file_path = Path(ydl.prepare_filename(info))
                task.file_size = task.file_path.stat().st_size if task.file_path.exists() else None
                task.metadata = {
                    "title": info.get("title"),
                    "duration": info.get("duration"),
                    "uploader": info.get("uploader"),
                    "view_count": info.get("view_count")
                }

            # Publish download completed
            await self.message_bus.publish(
                create_download_message(task.id, MessageType.DOWNLOAD_COMPLETED, {
                    "file_path": str(task.file_path),
                    "file_size": task.file_size,
                    "metadata": task.metadata
                })
            )

        except Exception as e:
            task.status = JobStatus.FAILED
            task.error = str(e)

            # Save resume data for potential retry
            await self._save_resume_data(task)

            raise

    async def _resume_download(self, task: DownloadTask, resume_data: ResumeData) -> None:
        """Resume a download from saved state"""
        try:
            # Publish resume started
            await self.message_bus.publish(
                create_download_message(task.id, MessageType.DOWNLOAD_RESUME, {})
            )

            # Configure yt-dlp with resume options
            ydl_opts = {
                'outtmpl': str(self.download_dir / '%(title)s.%(ext)s'),
                'continuedl': True,  # Enable resume
                'nooverwrites': True,
                'retries': 10,
                'fragment_retries': 10,
            }

            # Restore yt-dlp state if available
            if resume_data.yt_dlp_state:
                ydl_opts.update(resume_data.yt_dlp_state)

            def progress_hook(d):
                if d['status'] == 'downloading':
                    downloaded = d.get('downloaded_bytes', 0)
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    if total > 0:
                        progress = (downloaded / total) * 100
                        task.progress = progress

                        asyncio.create_task(self.message_bus.publish(
                            create_download_message(task.id, MessageType.DOWNLOAD_PROGRESS, {
                                "progress": progress,
                                "speed": d.get("speed"),
                                "eta": d.get("eta")
                            })
                        ))

            ydl_opts['progress_hooks'] = [progress_hook]

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(task.url, download=True)

                task.status = JobStatus.COMPLETED
                task.file_path = Path(ydl.prepare_filename(info))
                task.file_size = task.file_path.stat().st_size if task.file_path.exists() else None

            # Clear resume data on success
            await self._clear_resume_data(task.id)

            await self.message_bus.publish(
                create_download_message(task.id, MessageType.DOWNLOAD_COMPLETED, {
                    "file_path": str(task.file_path),
                    "file_size": task.file_size
                })
            )

        except Exception as e:
            task.status = JobStatus.FAILED
            task.error = str(e)
            raise

    def _get_ydl_opts(self, config: Dict[str, Any], task: DownloadTask) -> Dict[str, Any]:
        """Get yt-dlp options for download"""
        output_template = config.get('output_template', str(self.download_dir / '%(title)s.%(ext)s'))

        base_opts = {
            'outtmpl': output_template,
            'retries': config.get('max_retries', 10),
            'fragment_retries': config.get('fragment_retries', 10),
            'continuedl': True,  # Always enable resume capability
            'nooverwrites': True,
            'ignoreerrors': True,
        }

        # Audio-only configuration
        if config.get('audio_only', False):
            base_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'writethumbnail': True,
                'embedthumbnail': True,
            })
        else:
            # Video configuration
            format_pref = config.get('format_preference', 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best')
            base_opts.update({
                'format': format_pref,
                'merge_output_format': 'mp4',
            })

        return base_opts

    async def _save_resume_data(self, task: DownloadTask) -> None:
        """Save resume data for a task"""
        if task.file_path and task.file_path.exists():
            stat = task.file_path.stat()
            resume_data = ResumeData(
                url=task.url,
                file_path=task.file_path,
                downloaded_bytes=stat.st_size,
                last_modified=datetime.fromtimestamp(stat.st_mtime)
            )
            self.resume_data[task.id] = resume_data

            # Save to file for persistence
            resume_file = self.download_dir / f".resume_{task.id}.json"
            with open(resume_file, 'w') as f:
                json.dump({
                    'url': task.url,
                    'file_path': str(task.file_path),
                    'downloaded_bytes': stat.st_size,
                    'last_modified': stat.st_mtime,
                }, f)

    async def _load_resume_data(self, task_id: str) -> Optional[ResumeData]:
        """Load resume data for a task"""
        # Check memory first
        if task_id in self.resume_data:
            return self.resume_data[task_id]

        # Check file
        resume_file = self.download_dir / f".resume_{task_id}.json"
        if resume_file.exists():
            try:
                with open(resume_file, 'r') as f:
                    data = json.load(f)
                    return ResumeData(
                        url=data['url'],
                        file_path=Path(data['file_path']),
                        downloaded_bytes=data['downloaded_bytes'],
                        last_modified=datetime.fromtimestamp(data['last_modified'])
                    )
            except Exception:
                pass

        return None

    async def _clear_resume_data(self, task_id: str) -> None:
        """Clear resume data for a task"""
        if task_id in self.resume_data:
            del self.resume_data[task_id]

        resume_file = self.download_dir / f".resume_{task_id}.json"
        if resume_file.exists():
            resume_file.unlink()

# Global worker instance
download_worker = DownloadWorker()

# FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    await download_worker.connect()

    # Start message consumption
    consume_task = asyncio.create_task(download_worker.message_bus.start_consuming())

    yield

    # Graceful shutdown
    download_worker._shutdown = True
    consume_task.cancel()
    try:
        await consume_task
    except asyncio.CancelledError:
        pass

    await download_worker.disconnect()

app = FastAPI(
    title="Download Worker Service",
    description="Handles actual downloading with resume functionality",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "download-worker",
        "worker_id": download_worker.worker_id,
        "active_downloads": len(download_worker.active_downloads),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/active-downloads")
async def get_active_downloads():
    """Get active downloads"""
    return {
        "active_downloads": [
            {
                "task_id": task.id,
                "job_id": task.job_id,
                "url": task.url,
                "status": task.status.value,
                "progress": task.progress,
                "file_path": str(task.file_path) if task.file_path else None
            }
            for task in download_worker.active_downloads.values()
        ]
    }

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8002)),
        reload=False
    )