from yt_dlp import YoutubeDL
import os
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from config.config_manager import ConfigManager
from core.url_handler import get_content_type, validate_youtube_url
from core.file_manager import FileManager
from utils.logger import setup_logger

logger = setup_logger(__name__)

class YouTubeDownloader:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.file_manager = FileManager(config)
        self._stop_event = threading.Event()

    def get_modern_ydl_opts(self, audio_only: bool = False, is_live: bool = False) -> Dict:
        """Get modern yt-dlp options with current YouTube workarounds """
        base_opts = self.config.get_modern_ydl_opts().copy()

        # Set output template
        output_template = self.file_manager.get_output_template(audio_only)
        base_opts['outtmpl'] = output_template

        # Audio configuration
        if audio_only:
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
            base_opts['format'] = self.config.get('format_preference')
            base_opts['merge_output_format'] = 'mp4'

        # Live stream configuration
        if is_live:
            base_opts.update({
                'live_from_start': False,
                'wait_for_video': (30, 120),
                'retry_sleep_functions': {'http': lambda n: 5 + 2 * n},
            })

        # SponsorBlock integration
        if self.config.get('enable_sponsorblock'):
            base_opts['postprocessor_args'] = ['--sponsorblock-mark', 'all']

        return base_opts

    def download_single_video(self, url: str, audio_only: Optional[bool] = None) -> Dict:
        """Download a single video or live stream"""
        if audio_only is None:
            audio_only = self.config.get('audio_only', False)

        # Check if shutdown was requested
        if self._stop_event.is_set():
            return {
                'success': False,
                'url': url,
                'error': 'Download cancelled by user'
            }

        try:
            content_type = get_content_type(url)
            is_live = content_type == 'live'

            ydl_opts = self.get_modern_ydl_opts(audio_only, is_live)

            # Add progress hooks
            if hasattr(self, 'progress_hook'):
                ydl_opts['progress_hooks'] = [self.progress_hook]

            logger.info(f"Downloading {content_type}: {url}")

            # Check for shutdown before starting download
            if self._stop_event.is_set():
                return {
                    'success': False,
                    'url': url,
                    'error': 'Download cancelled by user'
                }

            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

                # Check if shutdown was requested during download
                if self._stop_event.is_set():
                    return {
                        'success': False,
                        'url': url,
                        'error': 'Download interrupted by user'
                    }

                return {
                    'success': True,
                    'url': url,
                    'title': info.get('title', 'Unknown'),
                    'duration': info.get('duration', 0),
                    'is_live': is_live,
                    'was_live': info.get('was_live', False)
                }

        except Exception as e:
            logger.error(f"Download failed for {url}: {str(e)}")
            return {
                'success': False,
                'url': url,
                'error': str(e)
            }

    def download_playlist(self, url: str, audio_only: Optional[bool] = None) -> Dict:
        """Download playlist with batch support"""
        if audio_only is None:
            audio_only = self.config.get('audio_only', False)

        # Check if shutdown was requested
        if self._stop_event.is_set():
            return {
                'success': False,
                'url': url,
                'error': 'Download cancelled by user'
            }

        try:
            ydl_opts = self.get_modern_ydl_opts(audio_only)
            ydl_opts['outtmpl'] = self.file_manager.get_playlist_output_template(audio_only)

            logger.info(f"Downloading playlist: {url}")

            # Check for shutdown before starting
            if self._stop_event.is_set():
                return {
                    'success': False,
                    'url': url,
                    'error': 'Download cancelled by user'
                }

            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

                # Check if shutdown was requested during download
                if self._stop_event.is_set():
                    return {
                        'success': False,
                        'url': url,
                        'error': 'Download interrupted by user'
                    }

                return {
                    'success': True,
                    'url': url,
                    'type': 'playlist',
                    'title': info.get('title', 'Unknown Playlist'),
                    'entry_count': len(info.get('entries', [])),
                    'downloaded_entries': sum(1 for e in info.get('entries', []) if e.get('requested_downloads'))
                }

        except Exception as e:
            logger.error(f"Playlist download failed for {url}: {str(e)}")
            return {
                'success': False,
                'url': url,
                'error': str(e)
            }

    def download_multiple_urls(self, urls: List[str], audio_only: Optional[bool] = None) -> List[Dict]:
        """Download multiple URLs with parallel processing"""
        if audio_only is None:
            audio_only = self.config.get('audio_only', False)

        max_workers = min(self.config.get('max_workers', 3), len(urls))
        results = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {
                executor.submit(self.download_single_item, url, audio_only): url
                for url in urls
            }

            for future in as_completed(future_to_url):
                # Check if shutdown was requested
                if self._stop_event.is_set():
                    logger.info("Shutdown requested, cancelling remaining downloads")
                    # Cancel remaining futures
                    for f in future_to_url:
                        if not f.done():
                            f.cancel()
                    break

                url = future_to_url[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    logger.error(f"Thread execution failed for {url}: {str(e)}")
                    results.append({
                        'success': False,
                        'url': url,
                        'error': str(e)
                    })

        return results

    def download_single_item(self, url: str, audio_only: bool) -> Dict:
        """Download a single item (video, playlist, or live stream)"""
        content_type = get_content_type(url)

        if content_type == 'playlist':
            return self.download_playlist(url, audio_only)
        else:
            return self.download_single_video(url, audio_only)

    def stop_all_downloads(self):
        """Stop all ongoing downloads"""
        self._stop_event.set()