import os
from typing import Optional
from config.config_manager import ConfigManager
from utils.logger import setup_logger

logger = setup_logger(__name__)

class FileManager:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.ensure_output_directory()

    def ensure_output_directory(self):
        """Ensure the output directory exists"""
        output_path = self.config.get('output_path')
        if not os.path.exists(output_path):
            os.makedirs(output_path, exist_ok=True)
            logger.info(f"Created output directory: {output_path}")

    def get_output_template(self, audio_only: bool = False) -> str:
        """Get output template for files"""
        output_path = self.config.get('output_path')

        if audio_only:
            return os.path.join(output_path, '%(title)s.%(ext)s')
        else:
            return os.path.join(output_path, '%(title)s [%(height)sp].%(ext)s')

    def get_playlist_output_template(self, audio_only: bool = False) -> str:
        """Get output template for playlist items"""
        output_path = self.config.get('output_path')

        if self.config.get('use_playlist_subdir', True):
            if audio_only:
                return os.path.join(output_path, '%(playlist_title)s', '%(title)s.%(ext)s')
            else:
                return os.path.join(output_path, '%(playlist_title)s', '%(title)s [%(height)sp].%(ext)s')
        else:
            if audio_only:
                return os.path.join(output_path, '%(playlist_title)s - %(title)s.%(ext)s')
            else:
                return os.path.join(output_path, '%(playlist_title)s - %(title)s [%(height)sp].%(ext)s')

    def sanitize_filename(self, filename: str) -> str:
        """Sanitize filename for filesystem compatibility"""
        # Remove or replace invalid characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')

        # Remove leading/trailing dots and spaces
        filename = filename.strip('. ')

        # Limit length
        if len(filename) > 255:
            filename = filename[:255]

        return filename

    def get_file_info(self, filepath: str) -> dict:
        """Get information about a downloaded file"""
        if not os.path.exists(filepath):
            return {}

        stat = os.stat(filepath)
        return {
            'path': filepath,
            'size': stat.st_size,
            'modified': stat.st_mtime,
            'exists': True
        }