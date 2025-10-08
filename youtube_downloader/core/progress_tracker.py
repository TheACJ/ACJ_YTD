from typing import Callable, Dict, Any
import logging
from tqdm import tqdm
from utils.logger import setup_logger

logger = setup_logger(__name__)

class ProgressTracker:
    def __init__(self, total_items: int = 0, description: str = "Downloading"):
        self.total_items = total_items
        self.description = description
        self.progress_bar = None
        self.current_item = 0

    def create_progress_bar(self, total: int = None):
        """Create a progress bar for downloads"""
        if total:
            self.total_items = total
        self.progress_bar = tqdm(
            total=self.total_items,
            desc=self.description,
            unit='file',
            ncols=100,
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]'
        )

    def progress_hook(self, d: Dict[str, Any]):
        """yt-dlp progress hook"""
        status = d.get('status')

        if status == 'downloading':
            # Update progress bar with download progress
            if self.progress_bar:
                downloaded_bytes = d.get('downloaded_bytes', 0)
                total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate', 0)

                if total_bytes > 0:
                    percentage = (downloaded_bytes / total_bytes) * 100
                    self.progress_bar.set_postfix({
                        'speed': d.get('speed', 0),
                        'eta': d.get('eta', 0),
                        'file': d.get('filename', '').split('/')[-1][:30]
                    })
                    # Note: tqdm doesn't directly support byte-level progress easily
                    # This is a simplified version

        elif status == 'finished':
            if self.progress_bar:
                self.current_item += 1
                self.progress_bar.update(1)
                self.progress_bar.set_postfix({'status': 'Processing...'})
                logger.info(f"Download completed: {d.get('filename', 'Unknown')}")

        elif status == 'error':
            logger.error(f"Download error: {d.get('error', 'Unknown error')}")

    def close(self):
        """Close the progress bar"""
        if self.progress_bar:
            self.progress_bar.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()