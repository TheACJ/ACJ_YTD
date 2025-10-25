from yt_dlp import YoutubeDL
import os
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import random

from config.config_manager import ConfigManager
from config.default_config import LIVE_STREAM_OPTS, COOKIE_OPTS
from core.url_handler import get_content_type, validate_youtube_url
from core.file_manager import FileManager
from utils.logger import setup_logger
from utils.auth import setup_youtube_auth

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

        # Live stream configuration with enhanced options
        if is_live:
            live_opts = LIVE_STREAM_OPTS.copy()
            # Customize wait times based on config
            live_opts['wait_for_video'] = (
                self.config.get('live_stream_wait', 30),
                self.config.get('live_stream_max_wait', 120)
            )
            base_opts.update(live_opts)

        # Cookie-based authentication for restricted content
        if self.config.get('use_cookies', True):
            try:
                cookie_file = setup_youtube_auth(self.config)
                if cookie_file:
                    base_opts['cookiefile'] = cookie_file
                    logger.info("YouTube authentication enabled with browser cookies")
                else:
                    logger.warning("Cookie authentication setup failed - proceeding without cookies")
            except Exception as e:
                logger.warning(f"Failed to setup cookie authentication: {e}")

        # Proxy support for geo-restricted content
        proxy_url = self.config.get('proxy_url')
        if proxy_url:
            base_opts['proxy'] = proxy_url
            logger.info(f"Using proxy: {proxy_url}")

        # SponsorBlock integration
        if self.config.get('enable_sponsorblock'):
            base_opts['postprocessor_args'] = ['--sponsorblock-mark', 'all']

        return base_opts

    def download_single_video(self, url: str, audio_only: Optional[bool] = None) -> Dict:
        """Download a single video or live stream with enhanced error handling"""
        if audio_only is None:
            audio_only = self.config.get('audio_only', False)

        # Check if shutdown was requested
        if self._stop_event.is_set():
            return {
                'success': False,
                'url': url,
                'error': 'Download cancelled by user'
            }

        content_type = get_content_type(url)
        is_live = content_type == 'live'

        # Implement retry logic for live streams and 403 errors
        max_retries = self.config.get('max_retries', 10)
        retry_count = 0

        while retry_count <= max_retries:
            try:
                ydl_opts = self.get_modern_ydl_opts(audio_only, is_live)

                # Add progress hooks
                if hasattr(self, 'progress_hook'):
                    ydl_opts['progress_hooks'] = [self.progress_hook]

                logger.info(f"Downloading {content_type}: {url} (attempt {retry_count + 1}/{max_retries + 1})")

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
                error_msg = str(e)
                logger.warning(f"Download attempt {retry_count + 1} failed for {url}: {error_msg}")

                # Check if this is a retryable error
                is_retryable = self._is_retryable_error(error_msg, is_live)

                if not is_retryable or retry_count >= max_retries:
                    logger.error(f"Download failed permanently for {url}: {error_msg}")
                    return {
                        'success': False,
                        'url': url,
                        'error': error_msg
                    }

                # Exponential backoff for retries
                retry_delay = self._calculate_retry_delay(retry_count, is_live)
                logger.info(f"Retrying in {retry_delay} seconds...")

                if self._stop_event.wait(timeout=retry_delay):
                    # Shutdown was requested during wait
                    return {
                        'success': False,
                        'url': url,
                        'error': 'Download cancelled by user'
                    }

                retry_count += 1

        # Should not reach here, but just in case
        return {
            'success': False,
            'url': url,
            'error': f'Max retries ({max_retries}) exceeded'
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

    def _is_retryable_error(self, error_msg: str, is_live: bool) -> bool:
        """Determine if an error is retryable"""
        retryable_patterns = [
            'HTTP Error 403',
            'HTTP Error 429',  # Too Many Requests
            'HTTP Error 502',  # Bad Gateway
            'HTTP Error 503',  # Service Unavailable
            'HTTP Error 504',  # Gateway Timeout
            'Connection reset',
            'Connection timed out',
            'Network is unreachable',
            'Temporary failure',
            'unable to download video data',
            'Fragment download failed',
        ]

        # For live streams, be more aggressive with retries
        if is_live:
            retryable_patterns.extend([
                'Live stream',
                'Stream ended',
                'Fragment unavailable',
            ])

        error_lower = error_msg.lower()
        return any(pattern.lower() in error_lower for pattern in retryable_patterns)

    def _calculate_retry_delay(self, retry_count: int, is_live: bool) -> float:
        """Calculate retry delay with exponential backoff"""
        base_delay = 5 if is_live else 2
        max_delay = 300  # 5 minutes max

        # Exponential backoff: base_delay * (2 ^ retry_count)
        delay = base_delay * (2 ** retry_count)

        # Add jitter to avoid thundering herd
        jitter = random.uniform(0.5, 1.5)
        delay *= jitter

        # Cap at maximum delay
        delay = min(delay, max_delay)

        return delay

    def stop_all_downloads(self):
        """Stop all ongoing downloads"""
        self._stop_event.set()