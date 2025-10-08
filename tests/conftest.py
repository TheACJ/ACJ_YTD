"""Test configuration and fixtures"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch

from youtube_downloader.config.config_manager import ConfigManager
from youtube_downloader.models.database import DatabaseManager
from youtube_downloader.models.data_models import DownloadConfig

@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)

@pytest.fixture
def mock_config(temp_dir):
    """Create a mock configuration manager"""
    config = ConfigManager()
    config.config['output_path'] = str(temp_dir / 'downloads')
    config.config['max_workers'] = 1  # Reduce for testing
    return config

@pytest.fixture
def test_db(temp_dir):
    """Create a test database"""
    db_path = temp_dir / 'test.db'
    db = DatabaseManager(str(db_path))
    yield db
    # Cleanup
    if db_path.exists():
        db_path.unlink()

@pytest.fixture
def sample_download_config(temp_dir):
    """Create a sample download configuration"""
    return DownloadConfig(
        output_path=temp_dir / 'downloads',
        audio_only=False,
        max_workers=2
    )

@pytest.fixture
def mock_yt_dlp():
    """Mock yt-dlp YoutubeDL class"""
    with patch('youtube_downloader.core.downloader.YoutubeDL') as mock_ydl:
        mock_instance = Mock()
        mock_instance.extract_info.return_value = {
            'title': 'Test Video',
            'duration': 120,
            'uploader': 'Test Channel'
        }
        mock_ydl.return_value.__enter__.return_value = mock_instance
        mock_ydl.return_value.__exit__.return_value = None
        yield mock_ydl