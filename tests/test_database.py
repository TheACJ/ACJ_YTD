"""Test database operations"""

import pytest
from datetime import datetime, timedelta

from youtube_downloader.models.database import DatabaseManager
from youtube_downloader.models.data_models import DownloadResult, DownloadJob, DownloadConfig

class TestDatabaseManager:
    def test_initialization(self, test_db):
        """Test database initialization"""
        assert test_db.db_path.exists()

    def test_save_and_get_download_job(self, test_db, sample_download_config):
        """Test saving and retrieving download jobs"""
        job = DownloadJob(
            id="test-job-123",
            urls=["https://youtu.be/test1", "https://youtu.be/test2"],
            config=sample_download_config,
            status="pending"
        )

        # Save job
        test_db.save_download_job(job)

        # Retrieve job
        retrieved = test_db.get_download_job("test-job-123")
        assert retrieved is not None
        assert retrieved.id == "test-job-123"
        assert len(retrieved.urls) == 2
        assert retrieved.status == "pending"

    def test_save_and_get_download_results(self, test_db):
        """Test saving and retrieving download results"""
        job_id = "test-job-results"

        results = [
            DownloadResult(
                success=True,
                url="https://youtu.be/test1",
                title="Test Video 1",
                duration=120,
                file_size=1024000
            ),
            DownloadResult(
                success=False,
                url="https://youtu.be/test2",
                error="Download failed"
            )
        ]

        # Save results
        for result in results:
            test_db.save_download_result(job_id, result)

        # Retrieve results
        retrieved = test_db.get_download_results(job_id)
        assert len(retrieved) == 2

        successful = [r for r in retrieved if r.success]
        failed = [r for r in retrieved if not r.success]

        assert len(successful) == 1
        assert len(failed) == 1
        assert successful[0].title == "Test Video 1"
        assert failed[0].error == "Download failed"

    def test_metrics_update(self, test_db):
        """Test metrics calculation and updates"""
        # Initial metrics
        initial = test_db.get_metrics()
        assert initial.total_downloads == 0

        # Add some results
        results = [
            DownloadResult(success=True, url="url1", file_size=1000, download_time=10.0),
            DownloadResult(success=True, url="url2", file_size=2000, download_time=15.0),
            DownloadResult(success=False, url="url3")
        ]

        test_db.update_metrics(results)

        # Check updated metrics
        updated = test_db.get_metrics()
        assert updated.total_downloads == 3
        assert updated.successful_downloads == 2
        assert updated.failed_downloads == 1
        assert updated.total_bytes_downloaded == 3000
        assert updated.average_download_time == 12.5  # (10+15)/2

    def test_cleanup_old_jobs(self, test_db, sample_download_config):
        """Test cleanup of old jobs"""
        # Create jobs with different dates
        old_date = datetime.now() - timedelta(days=40)
        recent_date = datetime.now() - timedelta(days=10)

        # Create old job
        old_job = DownloadJob(
            id="old-job",
            urls=["https://youtu.be/old"],
            config=sample_download_config,
            status="completed",
            created_at=old_date
        )

        # Create recent job
        recent_job = DownloadJob(
            id="recent-job",
            urls=["https://youtu.be/recent"],
            config=sample_download_config,
            status="completed",
            created_at=recent_date
        )

        test_db.save_download_job(old_job)
        test_db.save_download_job(recent_job)

        # Cleanup jobs older than 30 days
        deleted_count = test_db.cleanup_old_jobs(30)
        assert deleted_count == 1

        # Check that old job is gone
        assert test_db.get_download_job("old-job") is None
        # Check that recent job still exists
        assert test_db.get_download_job("recent-job") is not None