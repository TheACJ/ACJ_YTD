"""Database models and operations for enterprise-grade download tracking"""

import sqlite3
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path
import json
from contextlib import contextmanager
from .data_models import DownloadResult, DownloadJob, DownloadMetrics

class DatabaseManager:
    """SQLite database manager for download tracking and analytics"""

    def __init__(self, db_path: str = "downloads.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database tables"""
        with self._get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS download_jobs (
                    id TEXT PRIMARY KEY,
                    urls TEXT NOT NULL,
                    config TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    error TEXT
                )
            ''')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS download_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    success BOOLEAN NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT,
                    duration INTEGER,
                    error TEXT,
                    file_path TEXT,
                    content_type TEXT,
                    metadata TEXT,
                    timestamp TIMESTAMP NOT NULL,
                    file_size INTEGER,
                    download_time REAL,
                    FOREIGN KEY (job_id) REFERENCES download_jobs (id)
                )
            ''')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS download_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    total_downloads INTEGER DEFAULT 0,
                    successful_downloads INTEGER DEFAULT 0,
                    failed_downloads INTEGER DEFAULT 0,
                    total_bytes_downloaded INTEGER DEFAULT 0,
                    average_download_speed REAL DEFAULT 0.0,
                    average_download_time REAL DEFAULT 0.0,
                    last_updated TIMESTAMP NOT NULL
                )
            ''')

            # Insert initial metrics if not exists
            conn.execute('''
                INSERT OR IGNORE INTO download_metrics (id, last_updated)
                VALUES (1, ?)
            ''', (datetime.now(),))

            conn.commit()

    @contextmanager
    def _get_connection(self):
        """Get database connection with proper cleanup"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def save_download_job(self, job: DownloadJob) -> None:
        """Save a download job to database"""
        with self._get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO download_jobs
                (id, urls, config, status, created_at, started_at, completed_at, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                job.id,
                json.dumps(job.urls),
                json.dumps(job.config.__dict__ if hasattr(job.config, '__dict__') else job.config),
                job.status,
                job.created_at,
                job.started_at,
                job.completed_at,
                job.error
            ))
            conn.commit()

    def save_download_result(self, job_id: str, result: DownloadResult) -> None:
        """Save a download result to database"""
        with self._get_connection() as conn:
            conn.execute('''
                INSERT INTO download_results
                (job_id, success, url, title, duration, error, file_path,
                 content_type, metadata, timestamp, file_size, download_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                job_id,
                result.success,
                result.url,
                result.title,
                result.duration,
                result.error,
                str(result.file_path) if result.file_path else None,
                result.content_type,
                json.dumps(result.metadata) if result.metadata else None,
                result.timestamp,
                result.file_size,
                result.download_time
            ))
            conn.commit()

    def get_download_job(self, job_id: str) -> Optional[DownloadJob]:
        """Retrieve a download job by ID"""
        with self._get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM download_jobs WHERE id = ?',
                (job_id,)
            ).fetchone()

            if row:
                from .data_models import DownloadConfig
                urls = json.loads(row['urls'])
                config_dict = json.loads(row['config'])
                config = DownloadConfig(**config_dict)

                return DownloadJob(
                    id=row['id'],
                    urls=urls,
                    config=config,
                    status=row['status'],
                    created_at=datetime.fromisoformat(row['created_at']),
                    started_at=datetime.fromisoformat(row['started_at']) if row['started_at'] else None,
                    completed_at=datetime.fromisoformat(row['completed_at']) if row['completed_at'] else None,
                    error=row['error']
                )
        return None

    def get_download_results(self, job_id: str) -> List[DownloadResult]:
        """Get all results for a download job"""
        results = []
        with self._get_connection() as conn:
            rows = conn.execute(
                'SELECT * FROM download_results WHERE job_id = ? ORDER BY timestamp',
                (job_id,)
            ).fetchall()

            for row in rows:
                results.append(DownloadResult(
                    success=bool(row['success']),
                    url=row['url'],
                    title=row['title'],
                    duration=row['duration'],
                    error=row['error'],
                    file_path=Path(row['file_path']) if row['file_path'] else None,
                    content_type=row['content_type'],
                    metadata=json.loads(row['metadata']) if row['metadata'] else None,
                    timestamp=datetime.fromisoformat(row['timestamp']),
                    file_size=row['file_size'],
                    download_time=row['download_time']
                ))
        return results

    def update_metrics(self, results: List[DownloadResult]) -> None:
        """Update download metrics"""
        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful
        total_bytes = sum(r.file_size or 0 for r in results if r.success)
        avg_time = sum(r.download_time or 0 for r in results if r.success) / max(successful, 1)

        with self._get_connection() as conn:
            # Get current metrics
            current = conn.execute(
                'SELECT * FROM download_metrics WHERE id = 1'
            ).fetchone()

            new_total = current['total_downloads'] + len(results)
            new_successful = current['successful_downloads'] + successful
            new_failed = current['failed_downloads'] + failed
            new_bytes = current['total_bytes_downloaded'] + total_bytes

            # Calculate new averages
            if new_successful > 0:
                new_avg_time = ((current['average_download_time'] * current['successful_downloads']) +
                               (avg_time * successful)) / new_successful
                new_avg_speed = new_bytes / max(new_avg_time * new_successful, 1)
            else:
                new_avg_time = 0.0
                new_avg_speed = 0.0

            conn.execute('''
                UPDATE download_metrics SET
                    total_downloads = ?,
                    successful_downloads = ?,
                    failed_downloads = ?,
                    total_bytes_downloaded = ?,
                    average_download_speed = ?,
                    average_download_time = ?,
                    last_updated = ?
                WHERE id = 1
            ''', (
                new_total, new_successful, new_failed, new_bytes,
                new_avg_speed, new_avg_time, datetime.now()
            ))
            conn.commit()

    def get_metrics(self) -> DownloadMetrics:
        """Get current download metrics"""
        with self._get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM download_metrics WHERE id = 1'
            ).fetchone()

            return DownloadMetrics(
                total_downloads=row['total_downloads'],
                successful_downloads=row['successful_downloads'],
                failed_downloads=row['failed_downloads'],
                total_bytes_downloaded=row['total_bytes_downloaded'],
                average_download_speed=row['average_download_speed'],
                average_download_time=row['average_download_time'],
                last_updated=datetime.fromisoformat(row['last_updated'])
            )

    def cleanup_old_jobs(self, days: int = 30) -> int:
        """Clean up jobs older than specified days"""
        cutoff_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        cutoff_date = cutoff_date.replace(day=cutoff_date.day - days)

        with self._get_connection() as conn:
            # Delete old results first (foreign key constraint)
            conn.execute(
                'DELETE FROM download_results WHERE job_id IN (SELECT id FROM download_jobs WHERE created_at < ?)',
                (cutoff_date,)
            )

            # Delete old jobs
            cursor = conn.execute(
                'DELETE FROM download_jobs WHERE created_at < ?',
                (cutoff_date,)
            )

            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count