"""
Enhanced YouTube Downloader v4.0
Supports modern YouTube features with robust error handling and advanced capabilities
"""

from yt_dlp import YoutubeDL
import os
import re
import sys
import json
import time
import hashlib
import multiprocessing as mp
from multiprocessing import Process, Queue, Lock, Manager
from typing import Optional, List, Dict, Tuple, Any
from urllib.parse import urlparse, parse_qs
from functools import lru_cache
from tqdm import tqdm
import threading
from queue import Empty
import signal
from datetime import datetime, timedelta
import requests
from pathlib import Path
import sqlite3
import logging
from enum import Enum
import tempfile
import shutil

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('youtube_downloader.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class DownloadQuality(Enum):
    """Quality presets for downloads"""
    BEST = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    HIGH_1080P = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best"
    MEDIUM_720P = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best"
    LOW_480P = "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best"
    AUDIO_BEST = "bestaudio[ext=m4a]/bestaudio/best"
    AUDIO_MEDIUM = "bestaudio[abr<=192]/bestaudio/best"

class ContentType(Enum):
    """YouTube content types"""
    VIDEO = "video"
    PLAYLIST = "playlist"
    CHANNEL = "channel"
    SHORTS = "shorts"
    LIVE = "live"
    PREMIERE = "premiere"

# Enhanced default configuration
DEFAULT_CONFIG = {
    'batch_size': 10,
    'max_workers': 3,
    'audio_only': False,
    'output_path': './downloads',
    'max_retries': 5,
    'download_timeout': 3600,
    'format_preference': DownloadQuality.HIGH_1080P.value,
    'use_playlist_subdir': True,
    'download_subtitles': True,
    'embed_subtitles': True,
    'download_thumbnails': True,
    'embed_thumbnails': True,
    'download_metadata': True,
    'write_description': True,
    'write_info_json': True,
    'keep_video_after_extract': False,
    'use_cookies': False,
    'cookies_file': None,
    'use_proxy': False,
    'proxy_url': None,
    'rate_limit': None,  # bytes per second
    'sleep_interval': 1,  # seconds between downloads
    'max_sleep_interval': 5,
    'use_sponsorblock': False,
    'sponsorblock_remove': ['sponsor', 'intro', 'outro', 'selfpromo'],
    'split_chapters': False,
    'concurrent_fragments': 4,
    'use_aria2': False,
    'aria2_max_connections': 16,
    'geo_bypass': True,
    'age_limit': None,
    'archive_file': '.youtube_archive.txt',
    'use_archive': True,
    'prefer_free_formats': False,
    'extract_flat': False,
    'ignore_errors': True,
    'continue_on_error': True,
    'no_overwrites': True,
    'restrict_filenames': True,
    'windows_filenames': sys.platform == 'win32',
    'trim_file_name': 200,
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'referer': 'https://www.youtube.com/',
    'min_views': None,
    'max_views': None,
    'min_duration': None,
    'max_duration': None,
    'upload_date_after': None,
    'upload_date_before': None
}

class DatabaseManager:
    """SQLite database manager for persistent storage"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or os.path.join(os.path.dirname(__file__), 'youtube_downloader.db')
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Downloads table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT UNIQUE,
                    url TEXT,
                    title TEXT,
                    channel TEXT,
                    duration INTEGER,
                    filesize INTEGER,
                    format TEXT,
                    quality TEXT,
                    download_date TIMESTAMP,
                    file_path TEXT,
                    status TEXT,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    metadata TEXT
                )
            ''')
            
            # Playlists table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS playlists (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    playlist_id TEXT UNIQUE,
                    title TEXT,
                    channel TEXT,
                    video_count INTEGER,
                    downloaded_count INTEGER DEFAULT 0,
                    last_checked TIMESTAMP,
                    last_index INTEGER DEFAULT 0,
                    status TEXT
                )
            ''')
            
            # Channels table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT UNIQUE,
                    name TEXT,
                    subscriber_count INTEGER,
                    video_count INTEGER,
                    last_checked TIMESTAMP,
                    auto_download BOOLEAN DEFAULT 0
                )
            ''')
            
            conn.commit()
    
    def add_download(self, video_info: Dict) -> int:
        """Add download record to database"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO downloads 
                (video_id, url, title, channel, duration, filesize, format, quality, 
                 download_date, file_path, status, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                video_info.get('id'),
                video_info.get('webpage_url'),
                video_info.get('title'),
                video_info.get('uploader'),
                video_info.get('duration'),
                video_info.get('filesize'),
                video_info.get('format'),
                video_info.get('quality'),
                datetime.now(),
                video_info.get('file_path'),
                video_info.get('status', 'completed'),
                json.dumps(video_info.get('metadata', {}))
            ))
            return cursor.lastrowid
    
    def is_downloaded(self, video_id: str) -> bool:
        """Check if video was already downloaded"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM downloads WHERE video_id = ? AND status = 'completed'",
                (video_id,)
            )
            return cursor.fetchone()[0] > 0
    
    def get_failed_downloads(self, max_retries: int = 3) -> List[Dict]:
        """Get failed downloads that can be retried"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM downloads 
                WHERE status = 'failed' AND retry_count < ?
                ORDER BY download_date DESC
            ''', (max_retries,))
            
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

class CookieManager:
    """Manage browser cookies for authenticated downloads"""
    
    def __init__(self, browser: str = 'chrome'):
        self.browser = browser
        self.cookies_file = None
    
    def extract_cookies(self) -> str:
        """Extract cookies from browser"""
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        temp_file.close()
        
        try:
            # Use yt-dlp's cookie extraction
            ydl_opts = {
                'cookiesfrombrowser': (self.browser,),
                'cookiefile': temp_file.name,
                'quiet': True
            }
            
            with YoutubeDL(ydl_opts) as ydl:
                # Extract cookies by getting info from YouTube homepage
                ydl.extract_info('https://www.youtube.com', download=False)
            
            self.cookies_file = temp_file.name
            return temp_file.name
        except Exception as e:
            logger.error(f"Failed to extract cookies: {e}")
            if os.path.exists(temp_file.name):
                os.unlink(temp_file.name)
            return None
    
    def cleanup(self):
        """Clean up temporary cookie file"""
        if self.cookies_file and os.path.exists(self.cookies_file):
            os.unlink(self.cookies_file)

class NetworkManager:
    """Manage network settings and resilience"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.session = requests.Session()
        self.setup_session()
    
    def setup_session(self):
        """Setup requests session with proper headers and proxy"""
        self.session.headers.update({
            'User-Agent': self.config.get('user_agent'),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        
        if self.config.get('use_proxy') and self.config.get('proxy_url'):
            self.session.proxies = {
                'http': self.config['proxy_url'],
                'https': self.config['proxy_url']
            }
    
    def test_connection(self, url: str = 'https://www.youtube.com') -> bool:
        """Test connection to YouTube"""
        try:
            response = self.session.get(url, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
    
    def get_best_cdn(self) -> str:
        """Determine best CDN endpoint"""
        # YouTube CDN endpoints to test
        cdn_endpoints = [
            'https://www.youtube.com',
            'https://m.youtube.com',
            'https://youtubei.googleapis.com'
        ]
        
        best_cdn = None
        best_time = float('inf')
        
        for endpoint in cdn_endpoints:
            try:
                start = time.time()
                response = self.session.head(endpoint, timeout=5)
                elapsed = time.time() - start
                
                if response.status_code == 200 and elapsed < best_time:
                    best_time = elapsed
                    best_cdn = endpoint
            except:
                continue
        
        return best_cdn or 'https://www.youtube.com'

class SmartDownloader:
    """Enhanced downloader with intelligent features"""
    
    def __init__(self, config_manager: 'EnhancedConfigManager', db_manager: DatabaseManager):
        self.config = config_manager
        self.db = db_manager
        self.network = NetworkManager(config_manager.config)
        self.cookie_manager = None
        
    def get_optimized_format(self, info_dict: Dict, quality_preference: str = None) -> str:
        """Get optimized format based on available formats and network conditions"""
        formats = info_dict.get('formats', [])
        
        if not formats:
            return quality_preference or DownloadQuality.HIGH_1080P.value
        
        # Analyze available formats
        available_heights = set()
        available_codecs = set()
        
        for fmt in formats:
            if fmt.get('height'):
                available_heights.add(fmt['height'])
            if fmt.get('vcodec'):
                available_codecs.add(fmt['vcodec'])
        
        # Prefer VP9/AV1 for better quality
        codec_preference = []
        if 'av01' in available_codecs:
            codec_preference.append('[vcodec^=av01]')
        if 'vp9' in available_codecs:
            codec_preference.append('[vcodec^=vp9]')
        
        # Build format string based on available options
        if self.config.get('audio_only'):
            return DownloadQuality.AUDIO_BEST.value
        
        # Adaptive quality based on available heights
        if 2160 in available_heights and quality_preference == DownloadQuality.BEST.value:
            base_format = "bestvideo[height<=2160]"
        elif 1440 in available_heights and quality_preference in [DownloadQuality.BEST.value, DownloadQuality.HIGH_1080P.value]:
            base_format = "bestvideo[height<=1440]"
        elif 1080 in available_heights:
            base_format = "bestvideo[height<=1080]"
        elif 720 in available_heights:
            base_format = "bestvideo[height<=720]"
        else:
            base_format = "bestvideo"
        
        # Add codec preference if available
        if codec_preference:
            base_format += ''.join(codec_preference)
        
        # Complete format string
        return f"{base_format}+bestaudio/best"
    
    def create_ydl_opts(self, output_path: str, process_id: int = 0, 
                        progress_queue: Queue = None) -> Dict:
        """Create optimized yt-dlp options"""
        
        # Base options
        ydl_opts = {
            'outtmpl': os.path.join(output_path, '%(title).200s.%(ext)s'),
            'ignoreerrors': self.config.get('ignore_errors', True),
            'continue': True,
            'no_warnings': False,
            'quiet': False,
            'no_color': False,
            'extract_flat': self.config.get('extract_flat', False),
            
            # Network options
            'retries': self.config.get('max_retries', 5),
            'fragment_retries': self.config.get('max_retries', 5),
            'skip_unavailable_fragments': True,
            'keepvideo': self.config.get('keep_video_after_extract', False),
            'buffersize': 1024 * 16,  # 16KB buffer
            'http_chunk_size': 10485760,  # 10MB chunks
            
            # Format options
            'format': self.config.get('format_preference'),
            'merge_output_format': 'mp4' if not self.config.get('audio_only') else None,
            
            # Subtitle options
            'writesubtitles': self.config.get('download_subtitles', True),
            'writeautomaticsub': self.config.get('download_subtitles', True),
            'allsubtitles': True,
            'subtitlesformat': 'best',
            'subtitleslangs': ['en', 'en-US'],
            'embedsubtitles': self.config.get('embed_subtitles', True),
            
            # Thumbnail options
            'writethumbnail': self.config.get('download_thumbnails', True),
            'embedthumbnail': self.config.get('embed_thumbnails', True),
            
            # Metadata options
            'writedescription': self.config.get('write_description', True),
            'writeinfojson': self.config.get('write_info_json', True),
            'writeannotations': False,
            'writemetadata': True,
            'embedmetadata': True,
            
            # Post-processing
            'postprocessors': self._get_postprocessors(),
            
            # Authentication
            'username': None,
            'password': None,
            'twofactor': None,
            'usenetrc': False,
            
            # Age and geo bypass
            'age_limit': self.config.get('age_limit'),
            'geo_bypass': self.config.get('geo_bypass', True),
            'geo_bypass_country': 'US',
            
            # Rate limiting
            'ratelimit': self.config.get('rate_limit'),
            'sleep_interval': self.config.get('sleep_interval', 1),
            'max_sleep_interval': self.config.get('max_sleep_interval', 5),
            'sleep_interval_requests': 1,
            'sleep_interval_subtitles': 0,
            
            # Archive
            'download_archive': self.config.get('archive_file') if self.config.get('use_archive') else None,
            
            # Filename restrictions
            'restrictfilenames': self.config.get('restrict_filenames', True),
            'windowsfilenames': self.config.get('windows_filenames', sys.platform == 'win32'),
            'trim_file_name': self.config.get('trim_file_name', 200),
            
            # External downloader
            'external_downloader': self._get_external_downloader(),
            'external_downloader_args': self._get_external_downloader_args(),
            
            # Progress hooks
            'progress_hooks': [],
            
            # Match filters
            'match_filter': self._create_match_filter(),
        }
        
        # Add progress hook if provided
        if progress_queue:
            ydl_opts['progress_hooks'].append(
                self._create_progress_hook(process_id, progress_queue)
            )
        
        # Add cookies if configured
        if self.config.get('use_cookies'):
            if self.config.get('cookies_file'):
                ydl_opts['cookiefile'] = self.config.get('cookies_file')
            else:
                # Extract from browser
                if not self.cookie_manager:
                    self.cookie_manager = CookieManager()
                cookies_file = self.cookie_manager.extract_cookies()
                if cookies_file:
                    ydl_opts['cookiefile'] = cookies_file
        
        # Add proxy if configured
        if self.config.get('use_proxy') and self.config.get('proxy_url'):
            ydl_opts['proxy'] = self.config.get('proxy_url')
        
        # Add user agent and referer
        ydl_opts['http_headers'] = {
            'User-Agent': self.config.get('user_agent'),
            'Referer': self.config.get('referer')
        }
        
        return ydl_opts
    
    def _get_postprocessors(self) -> List[Dict]:
        """Get post-processors configuration"""
        postprocessors = []
        
        if self.config.get('audio_only'):
            # Audio extraction
            postprocessors.append({
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
                'nopostoverwrites': False
            })
        else:
            # Video conversion if needed
            postprocessors.append({
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4'
            })
        
        # Metadata embedding
        if self.config.get('embed_thumbnails'):
            postprocessors.append({
                'key': 'FFmpegThumbnailsConvertor',
                'format': 'jpg'
            })
            postprocessors.append({
                'key': 'EmbedThumbnail',
                'already_have_thumbnail': False
            })
        
        if self.config.get('embed_subtitles'):
            postprocessors.append({
                'key': 'FFmpegEmbedSubtitle'
            })
        
        postprocessors.append({
            'key': 'FFmpegMetadata',
            'add_metadata': True
        })
        
        # SponsorBlock
        if self.config.get('use_sponsorblock'):
            postprocessors.append({
                'key': 'SponsorBlock',
                'categories': self.config.get('sponsorblock_remove', ['sponsor'])
            })
            postprocessors.append({
                'key': 'ModifyChapters',
                'remove_sponsor_segments': self.config.get('sponsorblock_remove', ['sponsor'])
            })
        
        # Chapter splitting
        if self.config.get('split_chapters'):
            postprocessors.append({
                'key': 'FFmpegSplitChapters',
                'force_keyframes': False
            })
        
        return postprocessors
    
    def _get_external_downloader(self) -> Optional[str]:
        """Get external downloader if configured"""
        if self.config.get('use_aria2'):
            # Check if aria2c is available
            if shutil.which('aria2c'):
                return 'aria2c'
        return None
    
    def _get_external_downloader_args(self) -> Optional[Dict]:
        """Get external downloader arguments"""
        if self.config.get('use_aria2'):
            return {
                'aria2c': [
                    f'--max-connection-per-server={self.config.get("aria2_max_connections", 16)}',
                    '--min-split-size=1M',
                    '--max-concurrent-downloads=3',
                    '--auto-file-renaming=false',
                    '--continue=true',
                    '--retry-wait=3',
                    f'--max-tries={self.config.get("max_retries", 5)}'
                ]
            }
        return None
    
    def _create_match_filter(self):
        """Create match filter for video selection"""
        def match_filter(info_dict):
            # Duration filter
            duration = info_dict.get('duration')
            if duration:
                if self.config.get('min_duration') and duration < self.config.get('min_duration'):
                    return f"Duration {duration}s is less than minimum {self.config.get('min_duration')}s"
                if self.config.get('max_duration') and duration > self.config.get('max_duration'):
                    return f"Duration {duration}s is more than maximum {self.config.get('max_duration')}s"
            
            # View count filter
            view_count = info_dict.get('view_count')
            if view_count:
                if self.config.get('min_views') and view_count < self.config.get('min_views'):
                    return f"View count {view_count} is less than minimum {self.config.get('min_views')}"
                if self.config.get('max_views') and view_count > self.config.get('max_views'):
                    return f"View count {view_count} is more than maximum {self.config.get('max_views')}"
            
            # Upload date filter
            upload_date = info_dict.get('upload_date')
            if upload_date:
                upload_datetime = datetime.strptime(upload_date, '%Y%m%d')
                
                if self.config.get('upload_date_after'):
                    after_date = datetime.strptime(self.config.get('upload_date_after'), '%Y-%m-%d')
                    if upload_datetime < after_date:
                        return f"Upload date {upload_date} is before {self.config.get('upload_date_after')}"
                
                if self.config.get('upload_date_before'):
                    before_date = datetime.strptime(self.config.get('upload_date_before'), '%Y-%m-%d')
                    if upload_datetime > before_date:
                        return f"Upload date {upload_date} is after {self.config.get('upload_date_before')}"
            
            # Check if already downloaded
            video_id = info_dict.get('id')
            if video_id and self.db.is_downloaded(video_id):
                return f"Video {video_id} already downloaded"
            
            return None
        
        return match_filter
    
    def _create_progress_hook(self, process_id: int, progress_queue: Queue):
        """Create progress hook for tracking download progress"""
        def progress_hook(d):
            try:
                if d['status'] == 'downloading':
                    total_size = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    downloaded = d.get('downloaded_bytes', 0)
                    
                    if total_size > 0:
                        filename = os.path.basename(d.get('filename', 'Unknown'))
                        desc = f"[P{process_id}] {filename[:30]}{'...' if len(filename) > 30 else ''}"
                        
                        progress_queue.put({
                            'process_id': process_id,
                            'action': 'create',
                            'total': total_size,
                            'desc': desc
                        })
                        
                        speed = d.get('speed')
                        eta = d.get('eta')
                        postfix = ""
                        
                        if speed:
                            if speed > 1024*1024:
                                postfix = f"{speed/1024/1024:.1f} MB/s"
                            else:
                                postfix = f"{speed/1024:.1f} KB/s"
                        
                        if eta:
                            postfix += f" ETA: {eta}s"
                        
                        progress_queue.put({
                            'process_id': process_id,
                            'action': 'update',
                            'progress': downloaded,
                            'postfix': postfix
                        })
                
                elif d['status'] == 'finished':
                    # Save to database
                    video_info = d.get('info_dict', {})
                    if video_info:
                        self.db.add_download({
                            'id': video_info.get('id'),
                            'webpage_url': video_info.get('webpage_url'),
                            'title': video_info.get('title'),
                            'uploader': video_info.get('uploader'),
                            'duration': video_info.get('duration'),
                            'filesize': d.get('total_bytes'),
                            'format': video_info.get('format'),
                            'quality': video_info.get('height'),
                            'file_path': d.get('filename'),
                            'status': 'completed',
                            'metadata': {
                                'description': video_info.get('description'),
                                'upload_date': video_info.get('upload_date'),
                                'view_count': video_info.get('view_count'),
                                'like_count': video_info.get('like_count')
                            }
                        })
                    
                    progress_queue.put({
                        'process_id': process_id,
                        'action': 'close'
                    })
                
                elif d['status'] == 'error':
                    logger.error(f"Download error: {d.get('error')}")
                    progress_queue.put({
                        'process_id': process_id,
                        'action': 'close'
                    })
                    
            except Exception as e:
                logger.error(f"Progress hook error: {e}")
        
        return progress_hook
    
    def download_with_retry(self, url: str, ydl_opts: Dict, max_retries: int = 3) -> Tuple[bool, Any]:
        """Download with intelligent retry and fallback"""
        
        for attempt in range(max_retries):
            try:
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    return True, info
                    
            except Exception as e:
                logger.error(f"Download attempt {attempt + 1} failed: {e}")
                
                # Intelligent retry with different strategies
                if attempt < max_retries - 1:
                    # Try different quality on retry
                    if 'format' in ydl_opts:
                        if attempt == 1:
                            # Fallback to 720p
                            ydl_opts['format'] = DownloadQuality.MEDIUM_720P.value
                            logger.info("Retrying with 720p quality...")
                        elif attempt == 2:
                            # Fallback to 480p
                            ydl_opts['format'] = DownloadQuality.LOW_480P.value
                            logger.info("Retrying with 480p quality...")
                    
                    # Increase sleep interval
                    time.sleep(2 ** attempt)
                else:
                    return False, str(e)
        
        return False, "Max retries exceeded"

class EnhancedConfigManager:
    """Enhanced configuration manager with validation and persistence"""
    
    def __init__(self, config_file: str = None):
        self.config_file = config_file or os.path.join(os.path.dirname(__file__), 'download_config.json')
        self.config = DEFAULT_CONFIG.copy()
        self.load_config()
        self.validate_config()
    
    def load_config(self):
        """Load configuration from file"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                self.config.update(user_config)
                logger.info(f"Loaded configuration from {self.config_file}")
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load config file: {e}. Using defaults.")
        else:
            self.save_config()
    
    def save_config(self):
        """Save current configuration to file"""
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False, default=str)
            logger.info(f"Configuration saved to {self.config_file}")
        except Exception as e:
            logger.error(f"Could not save config file: {e}")
    
    def validate_config(self):
        """Validate configuration values"""
        # Validate paths
        if not os.path.exists(self.config['output_path']):
            os.makedirs(self.config['output_path'], exist_ok=True)
        
        # Validate numeric ranges
        self.config['max_workers'] = max(1, min(10, self.config['max_workers']))
        self.config['batch_size'] = max(1, min(50, self.config['batch_size']))
        self.config['max_retries'] = max(1, min(10, self.config['max_retries']))
        
        # Validate quality preference
        if self.config['format_preference'] not in [q.value for q in DownloadQuality]:
            self.config['format_preference'] = DownloadQuality.HIGH_1080P.value
        
        # Validate proxy URL
        if self.config.get('use_proxy') and self.config.get('proxy_url'):
            if not self.config['proxy_url'].startswith(('http://', 'https://', 'socks5://')):
                logger.warning("Invalid proxy URL format. Disabling proxy.")
                self.config['use_proxy'] = False
    
    def get(self, key, default=None):
        """Get a configuration value"""
        return self.config.get(key, default)
    
    def set(self, key, value):
        """Set a configuration value"""
        self.config[key] = value
        self.validate_config()
        self.save_config()

def enhanced_download_worker(process_id: int, url: str, output_path: str, 
                            progress_queue: Queue, result_queue: Queue,
                            config: EnhancedConfigManager) -> None:
    """Enhanced worker process for downloading"""
    
    # Initialize components
    db_manager = DatabaseManager()
    smart_downloader = SmartDownloader(config, db_manager)
    
    try:
        # Create optimized yt-dlp options
        ydl_opts = smart_downloader.create_ydl_opts(output_path, process_id, progress_queue)
        
        # Perform download with retry
        success, result = smart_downloader.download_with_retry(url, ydl_opts, config.get('max_retries', 3))
        
        if success:
            result_queue.put({
                'url': url,
                'process_id': process_id,
                'success': True,
                'message': f"✅ [Process {process_id}] Download completed successfully!",
                'info': result
            })
        else:
            result_queue.put({
                'url': url,
                'process_id': process_id,
                'success': False,
                'message': f"❌ [Process {process_id}] Download failed: {result}"
            })
    
    except Exception as e:
        logger.error(f"Worker {process_id} error: {e}")
        result_queue.put({
            'url': url,
            'process_id': process_id,
            'success': False,
            'message': f"❌ [Process {process_id}] Error: {str(e)}"
        })
    
    finally:
        # Cleanup
        if smart_downloader.cookie_manager:
            smart_downloader.cookie_manager.cleanup()
        
        progress_queue.put({
            'process_id': process_id,
            'action': 'close'
        })

def download_youtube_enhanced(urls: List[str], config: EnhancedConfigManager = None) -> None:
    """
    Enhanced YouTube download with modern features
    """
    if not config:
        config = EnhancedConfigManager()
    
    # Initialize database
    db_manager = DatabaseManager()
    
    # Check network connectivity
    network = NetworkManager(config.config)
    if not network.test_connection():
        logger.error("Failed to connect to YouTube. Check your internet connection.")
        return
    
    output_path = config.get('output_path', './downloads')
    max_workers = config.get('max_workers', 3)
    
    os.makedirs(output_path, exist_ok=True)
    
    # Initialize multiprocessing
    mp.set_start_method('spawn', force=True)
    progress_queue = Queue()
    result_queue = Queue()
    
    # Initialize progress manager
    from .enhanced_components import EnhancedProgressManager
    progress_manager = EnhancedProgressManager(max_workers)
    progress_manager.start_monitoring()
    
    print(f"\n🚀 Enhanced YouTube Downloader v4.0")
    print(f"📁 Output: {output_path}")
    print(f"⚡ Workers: {max_workers}")
    print(f"🎯 Quality: {config.get('format_preference')}")
    print(f"📊 URLs to process: {len(urls)}")
    
    # Show enabled features
    features = []
    if config.get('download_subtitles'):
        features.append("Subtitles")
    if config.get('download_thumbnails'):
        features.append("Thumbnails")
    if config.get('use_sponsorblock'):
        features.append("SponsorBlock")
    if config.get('use_archive'):
        features.append("Archive Mode")
    if config.get('use_cookies'):
        features.append("Authentication")
    if config.get('use_proxy'):
        features.append("Proxy")
    if config.get('use_aria2'):
        features.append("Aria2c")
    
    if features:
        print(f"✨ Features: {', '.join(features)}")
    
    print("-" * 60)
    
    processes = []
    results = []
    
    try:
        # Start initial batch of processes
        for i, url in enumerate(urls[:max_workers]):
            process = Process(
                target=enhanced_download_worker,
                args=(i+1, url, output_path, progress_queue, result_queue, config)
            )
            process.start()
            processes.append(process)
        
        # Handle remaining URLs and collect results
        remaining_urls = urls[max_workers:]
        completed_count = 0
        
        while completed_count < len(urls):
            try:
                result = result_queue.get(timeout=1)
                results.append(result)
                completed_count += 1
                
                print(f"\n{result['message']}")
                
                # Start next download if URLs remaining
                if remaining_urls:
                    next_url = remaining_urls.pop(0)
                    process_id = result['process_id']
                    
                    for i, process in enumerate(processes):
                        if not process.is_alive():
                            process.join()
                            
                            new_process = Process(
                                target=enhanced_download_worker,
                                args=(process_id, next_url, output_path, 
                                     progress_queue, result_queue, config)
                            )
                            new_process.start()
                            processes[i] = new_process
                            break
            
            except Empty:
                continue
            except Exception as e:
                logger.error(f"Process management error: {e}")
                continue
    
    except KeyboardInterrupt:
        print("\n🛑 Download interrupted by user")
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join()
    
    finally:
        progress_manager.stop_monitoring()
        
        # Wait for all processes
        for process in processes:
            if process.is_alive():
                process.join(timeout=5)
                if process.is_alive():
                    process.terminate()
                    process.join()
    
    # Print summary
    print("\n" + "=" * 60)
    print("📊 DOWNLOAD SUMMARY")
    print("=" * 60)
    
    successful = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]
    
    print(f"✅ Successful: {len(successful)}")
    print(f"❌ Failed: {len(failed)}")
    
    if failed:
        print("\n❌ Failed URLs:")
        for result in failed:
            print(f"   • {result['url']}")
            print(f"     {result['message']}")
    
    # Show retry options for failed downloads
    if failed:
        print("\n💡 To retry failed downloads, run with --retry-failed flag")
    
    # Show archive information
    if config.get('use_archive'):
        archive_file = config.get('archive_file')
        if os.path.exists(archive_file):
            with open(archive_file, 'r') as f:
                archived_count = len(f.readlines())
            print(f"\n📚 Archive: {archived_count} videos tracked")

if __name__ == "__main__":
    # Parse command line arguments
    import argparse
    
    parser = argparse.ArgumentParser(description='Enhanced YouTube Downloader v4.0')
    parser.add_argument('urls', nargs='*', help='YouTube URLs to download')
    parser.add_argument('--audio-only', action='store_true', help='Download audio only')
    parser.add_argument('--quality', choices=['best', '1080p', '720p', '480p', 'audio'], 
                       default='1080p', help='Video quality')
    parser.add_argument('--output', '-o', default='./downloads', help='Output directory')
    parser.add_argument('--workers', type=int, default=3, help='Number of concurrent workers')
    parser.add_argument('--cookies-from-browser', choices=['chrome', 'firefox', 'safari', 'edge'],
                       help='Extract cookies from browser')
    parser.add_argument('--proxy', help='Proxy URL')
    parser.add_argument('--no-sponsorblock', action='store_true', help='Disable SponsorBlock')
    parser.add_argument('--retry-failed', action='store_true', help='Retry failed downloads')
    parser.add_argument('--config', help='Configuration file path')
    
    args = parser.parse_args()
    
    # Initialize configuration
    config = EnhancedConfigManager(args.config)
    
    # Update configuration from arguments
    if args.audio_only:
        config.set('audio_only', True)
    
    if args.quality:
        quality_map = {
            'best': DownloadQuality.BEST.value,
            '1080p': DownloadQuality.HIGH_1080P.value,
            '720p': DownloadQuality.MEDIUM_720P.value,
            '480p': DownloadQuality.LOW_480P.value,
            'audio': DownloadQuality.AUDIO_BEST.value
        }
        config.set('format_preference', quality_map.get(args.quality))
    
    if args.output:
        config.set('output_path', args.output)
    
    if args.workers:
        config.set('max_workers', args.workers)
    
    if args.cookies_from_browser:
        config.set('use_cookies', True)
        config.set('cookies_browser', args.cookies_from_browser)
    
    if args.proxy:
        config.set('use_proxy', True)
        config.set('proxy_url', args.proxy)
    
    if args.no_sponsorblock:
        config.set('use_sponsorblock', False)
    
    # Handle retry failed
    if args.retry_failed:
        db = DatabaseManager()
        failed = db.get_failed_downloads()
        if failed:
            urls = [f['url'] for f in failed]
            print(f"Found {len(urls)} failed downloads to retry")
            download_youtube_enhanced(urls, config)
        else:
            print("No failed downloads to retry")
    elif args.urls:
        download_youtube_enhanced(args.urls, config)
    else:
        # Interactive mode
        print("Enhanced YouTube Downloader v4.0")
        print("-" * 40)
        urls_input = input("Enter YouTube URLs (comma or space separated): ")
        urls = [u.strip() for u in re.split(r'[,\s]+', urls_input) if u.strip()]
        
        if urls:
            download_youtube_enhanced(urls, config)
        else:
            print("No URLs provided")