"""
ACJ YouTube Downloader — core downloader
Supports: restricted videos, age-gated, geo-blocked, live streams
"""
from yt_dlp import YoutubeDL
import os
import time
import threading
import random
from typing import Dict, List, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from config.config_manager import ConfigManager
from config.default_config import LIVE_STREAM_OPTS
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
        # Injected by main.py: (url: str) -> yt-dlp progress hook callable
        self._progress_hook_factory: Optional[Callable] = None


    # ─────────────────────────────────────────────────────────────────────────
    # yt-dlp options builder
    # ─────────────────────────────────────────────────────────────────────────
    def get_modern_ydl_opts(
        self,
        audio_only: bool = False,
        is_live: bool = False,
        url: str = "",
        skip_cookies: bool = False,
    ) -> Dict:
        base_opts = self.config.get_modern_ydl_opts().copy()
        base_opts['outtmpl'] = self.file_manager.get_output_template(audio_only)

        # ── Format ────────────────────────────────────────────────────────────
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
            base_opts['format'] = self.config.get('format_preference')
            base_opts['merge_output_format'] = 'mp4'

        # ── Live stream ───────────────────────────────────────────────────────
        if is_live:
            live_opts = LIVE_STREAM_OPTS.copy()
            live_opts['wait_for_video'] = (
                self.config.get('live_stream_wait', 30),
                self.config.get('live_stream_max_wait', 120),
            )
            base_opts.update(live_opts)


        # ── Restricted / age-gated bypass ─────────────────────────────────────
        # player_client order: web → android → tv_embedded
        # tv_embedded bypasses age gates without login
        # android bypasses most bot-check 403s
        base_opts['extractor_args'] = {
            'youtube': {
                'player_client': ['web', 'android', 'tv_embedded'],
                'player_skip': [],
            }
        }
        base_opts['geo_bypass'] = self.config.get('bypass_geo_restriction', True)

        # ── Cookie authentication ─────────────────────────────────────────────
        # skip_cookies=True is set on the fallback attempt when the browser
        # DB is locked or unavailable, so yt-dlp still runs cookieless.
        if not skip_cookies and self.config.get('use_cookies', True):
            self._attach_cookies(base_opts)

        # ── Proxy ─────────────────────────────────────────────────────────────
        proxy_url = self.config.get('proxy_url')
        if proxy_url:
            base_opts['proxy'] = proxy_url

        # ── Subtitles ─────────────────────────────────────────────────────────
        base_opts.update({
            'writesubtitles':   True,
            'writeautomaticsub': True,
            'subtitleslangs':   ['en'],
            'subtitlesformat':  'best',
            'embedsubtitles':   True,
        })

        # ── Archive ───────────────────────────────────────────────────────────
        if self.config.get('use_archive'):
            base_opts['download_archive'] = self.config.get('archive_file')

        # ── Progress hook ─────────────────────────────────────────────────────
        if self._progress_hook_factory and url:
            base_opts['progress_hooks'] = [self._progress_hook_factory(url)]

        return base_opts


    # ─────────────────────────────────────────────────────────────────────────
    # Cookie helpers
    # ─────────────────────────────────────────────────────────────────────────
    def _attach_cookies(self, opts: Dict) -> None:
        """
        Priority order:
          1. Manual cookiefile (always works, browser can be open)
          2. cookiesfrombrowser (browser must be closed on Windows)
          3. setup_youtube_auth JSON→Netscape conversion
        Each method is tried silently; failures are logged, not raised.
        """
        browser = self.config.get('browser_cookies', 'chrome')
        manual_file = self.config.get('cookies_file')

        # 1 ── Manual file takes priority (never locked, always portable)
        if manual_file and Path(manual_file).exists():
            opts['cookiefile'] = manual_file
            logger.info(f"Cookie source: manual file → {manual_file}")
            return

        # 2 ── cookiesfrombrowser (yt-dlp native, handles DPAPI decryption)
        if browser in ('chrome', 'firefox', 'edge', 'brave', 'opera', 'safari'):
            opts['cookiesfrombrowser'] = (browser,)
            logger.info(f"Cookie source: {browser} (cookiesfrombrowser)")
            return

        # 3 ── JSON → Netscape conversion via auth helper
        try:
            cookie_file = setup_youtube_auth(self.config)
            if cookie_file:
                opts['cookiefile'] = cookie_file
                logger.info(f"Cookie source: setup_youtube_auth → {cookie_file}")
        except Exception as e:
            logger.warning(f"Cookie setup failed ({e}) — will proceed without cookies")

    # ─────────────────────────────────────────────────────────────────────────
    # Single video download  (with cookie-locked fallback)
    # ─────────────────────────────────────────────────────────────────────────
    def download_single_video(self, url: str, audio_only: Optional[bool] = None) -> Dict:
        if audio_only is None:
            audio_only = self.config.get('audio_only', False)

        if self._stop_event.is_set():
            return {'success': False, 'url': url, 'error': 'Cancelled'}

        content_type = get_content_type(url)
        is_live      = content_type == 'live'
        max_retries  = self.config.get('max_retries', 10)

        # We run two passes:
        #   pass 0 — with cookies (normal)
        #   pass 1 — without cookies (fallback when browser DB is locked / unavailable)
        # Each pass still gets max_retries for transient network errors.
        for cookie_pass in range(2):
            skip_cookies = (cookie_pass == 1)
            if skip_cookies:
                logger.warning("Cookie load failed — retrying WITHOUT cookies (tv_embedded client will handle age-gate)")

            for attempt in range(max_retries + 1):
                if self._stop_event.is_set():
                    return {'success': False, 'url': url, 'error': 'Cancelled'}

                try:
                    ydl_opts = self.get_modern_ydl_opts(audio_only, is_live, url, skip_cookies)
                    logger.info(
                        f"[pass {cookie_pass+1}/2 attempt {attempt+1}/{max_retries+1}] "
                        f"{'(no cookies) ' if skip_cookies else ''}{url}"
                    )

                    with YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)

                    if self._stop_event.is_set():
                        return {'success': False, 'url': url, 'error': 'Interrupted'}

                    if info is None:
                        return {'success': False, 'url': url, 'error': 'No info extracted'}

                    return {
                        'success':  True,
                        'url':      url,
                        'title':    info.get('title', 'Unknown'),
                        'duration': info.get('duration', 0),
                        'is_live':  is_live,
                        'was_live': info.get('was_live', False),
                    }

                except Exception as e:
                    err = str(e)
                    logger.warning(f"Pass {cookie_pass+1} attempt {attempt+1} failed: {err}")

                    # Cookie errors → break inner loop, go to cookieless pass
                    if self._is_cookie_error(err):
                        logger.warning("Cookie error detected — switching to cookieless pass")
                        break  # exits attempt loop, outer loop increments cookie_pass

                    # Non-retryable → give up entirely
                    if not self._is_retryable_error(err, is_live) or attempt >= max_retries:
                        if cookie_pass == 0:
                            break  # try cookieless pass before giving up
                        return {'success': False, 'url': url, 'error': err}

                    delay = self._retry_delay(attempt, is_live)
                    logger.info(f"Retrying in {delay:.1f}s…")
                    if self._stop_event.wait(timeout=delay):
                        return {'success': False, 'url': url, 'error': 'Cancelled during retry'}

        return {'success': False, 'url': url, 'error': 'All download passes failed'}


    # ─────────────────────────────────────────────────────────────────────────
    # Playlist / channel download
    # ─────────────────────────────────────────────────────────────────────────
    def download_playlist(self, url: str, audio_only: Optional[bool] = None) -> Dict:
        if audio_only is None:
            audio_only = self.config.get('audio_only', False)

        if self._stop_event.is_set():
            return {'success': False, 'url': url, 'error': 'Cancelled'}

        for cookie_pass in range(2):
            skip_cookies = (cookie_pass == 1)
            try:
                ydl_opts = self.get_modern_ydl_opts(audio_only, url=url, skip_cookies=skip_cookies)
                ydl_opts['outtmpl'] = self.file_manager.get_playlist_output_template(audio_only)
                logger.info(f"Downloading playlist {'(no cookies) ' if skip_cookies else ''}: {url}")

                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)

                if self._stop_event.is_set():
                    return {'success': False, 'url': url, 'error': 'Interrupted'}

                entries = info.get('entries', []) if info else []
                return {
                    'success':            True,
                    'url':                url,
                    'type':               'playlist',
                    'title':              info.get('title', 'Unknown') if info else 'Unknown',
                    'entry_count':        len(entries),
                    'downloaded_entries': sum(1 for e in entries if e and e.get('requested_downloads')),
                }

            except Exception as e:
                err = str(e)
                if self._is_cookie_error(err) and cookie_pass == 0:
                    logger.warning(f"Cookie error on playlist — retrying without cookies: {err}")
                    continue
                logger.error(f"Playlist failed for {url}: {err}")
                return {'success': False, 'url': url, 'error': err}

        return {'success': False, 'url': url, 'error': 'Playlist download failed on all passes'}

    # ─────────────────────────────────────────────────────────────────────────
    # Dispatcher
    # ─────────────────────────────────────────────────────────────────────────
    def download_single_item(self, url: str, audio_only: bool) -> Dict:
        content_type = get_content_type(url)
        if content_type in ('playlist', 'channel'):
            return self.download_playlist(url, audio_only)
        return self.download_single_video(url, audio_only)

    # ─────────────────────────────────────────────────────────────────────────
    # Batch download  (API compatibility)
    # ─────────────────────────────────────────────────────────────────────────
    def download_multiple_urls(self, urls: List[str], audio_only: Optional[bool] = None) -> List[Dict]:
        if audio_only is None:
            audio_only = self.config.get('audio_only', False)

        results = []
        max_workers = min(self.config.get('max_workers', 3), len(urls))

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(self.download_single_item, u, audio_only): u for u in urls}
            for fut in as_completed(futures):
                if self._stop_event.is_set():
                    for f in futures:
                        f.cancel()
                    break
                url = futures[fut]
                try:
                    results.append(fut.result())
                except Exception as e:
                    results.append({'success': False, 'url': url, 'error': str(e)})

        return results


    # ─────────────────────────────────────────────────────────────────────────
    # Error classification
    # ─────────────────────────────────────────────────────────────────────────
    def _is_cookie_error(self, error_msg: str) -> bool:
        """
        Errors that mean the browser cookie DB could not be read.
        These are NOT retryable with cookies — we must switch to cookieless mode.
        """
        cookie_patterns = [
            'failed to load cookies',
            'could not copy',
            'could not read',
            'unable to load cookies',
            'cannot load cookies',
            'cookiesfrombrowser',
            'keyring',
            'dpapi',
            'sqlite',                   # DB locked by running browser
            'database is locked',
            'no such table',
            'unable to open database',
        ]
        low = error_msg.lower()
        return any(p in low for p in cookie_patterns)

    def _is_retryable_error(self, error_msg: str, is_live: bool) -> bool:
        """Transient network / server errors worth retrying."""
        patterns = [
            'HTTP Error 403',
            'HTTP Error 429',
            'HTTP Error 500',
            'HTTP Error 502',
            'HTTP Error 503',
            'HTTP Error 504',
            'Connection reset',
            'Connection timed out',
            'Network is unreachable',
            'Temporary failure',
            'unable to download video data',
            'Fragment download failed',
            'Sign in to confirm',       # may succeed with different player client
        ]
        if is_live:
            patterns += ['Live stream', 'Stream ended', 'Fragment unavailable']

        low = error_msg.lower()
        return any(p.lower() in low for p in patterns)

    def _retry_delay(self, attempt: int, is_live: bool) -> float:
        base  = 5.0 if is_live else 2.0
        delay = min(base * (2 ** attempt), 300.0)
        return delay * random.uniform(0.8, 1.2)

    # ─────────────────────────────────────────────────────────────────────────
    # Shutdown
    # ─────────────────────────────────────────────────────────────────────────
    def stop_all_downloads(self):
        self._stop_event.set()
