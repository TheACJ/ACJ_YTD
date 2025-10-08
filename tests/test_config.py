"""Test configuration management"""

import pytest
import os
from pathlib import Path

from youtube_downloader.config.config_manager import ConfigManager

class TestConfigManager:
    def test_initialization(self, temp_dir):
        """Test config manager initialization"""
        config = ConfigManager()
        assert config.get('output_path') == './downloads'
        assert config.get('max_workers') == 3

    def test_environment_variables(self, temp_dir, monkeypatch):
        """Test loading configuration from environment variables"""
        monkeypatch.setenv('YTD_OUTPUT_PATH', str(temp_dir / 'custom_downloads'))
        monkeypatch.setenv('YTD_MAX_WORKERS', '5')
        monkeypatch.setenv('YTD_AUDIO_ONLY', 'true')

        config = ConfigManager()
        assert config.get('output_path') == str(temp_dir / 'custom_downloads')
        assert config.get('max_workers') == 5
        assert config.get('audio_only') is True

    def test_config_validation(self, temp_dir):
        """Test configuration validation"""
        config = ConfigManager()
        config.set('max_workers', -1)
        assert config.get('max_workers') == 1  # Should be corrected

        config.set('download_timeout', 0)
        assert config.get('download_timeout') == 3600  # Should be corrected

    def test_config_file_operations(self, temp_dir):
        """Test saving and loading configuration from file"""
        config_file = temp_dir / 'test_config.json'
        config = ConfigManager(str(config_file))

        # Modify config
        config.set('max_workers', 10)
        config.set('audio_only', True)
        config.save_config()

        # Create new instance and load
        config2 = ConfigManager(str(config_file))
        assert config2.get('max_workers') == 10
        assert config2.get('audio_only') is True

    def test_reset_to_defaults(self):
        """Test resetting configuration to defaults"""
        config = ConfigManager()
        original_workers = config.get('max_workers')

        config.set('max_workers', 99)
        assert config.get('max_workers') == 99

        config.reset_to_defaults()
        assert config.get('max_workers') == original_workers