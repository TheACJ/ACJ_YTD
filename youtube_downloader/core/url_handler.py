from yt_dlp import YoutubeDL
from urllib.parse import urlparse, parse_qs
from functools import lru_cache
from typing import Tuple, Dict
import re

@lru_cache(maxsize=128)
def get_url_info(url: str) -> Tuple[str, Dict]:
    """
    Get URL information with caching and modern YouTube URL support
    Returns 'video', 'playlist', 'channel', 'live', or 'shorts'
    """
    try:
        ydl_opts = {
            'quiet': True,
            'extract_flat': True,
            'no_warnings': True,
            'skip_download': True,
        }

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            if info is None:
                return _fallback_url_detection(url), {}

            content_type = info.get('_type', 'video')

            # Enhanced live stream and shorts detection
            if _is_live_stream(url, info):
                return 'live', info
            elif _is_shorts(url):
                return 'shorts', info
            elif content_type == 'playlist':
                return 'playlist', info
            else:
                return content_type, info

    except Exception:
        return _fallback_url_detection(url), {}

def _is_live_stream(url: str, info: Dict) -> bool:
    """Check if URL is a live stream"""
    url_lower = url.lower()
    return (
        '/live/' in url_lower or
        '/watch?v=' in url_lower and '&live=1' in url_lower or
        info.get('is_live') or
        info.get('was_live') or
        info.get('live_status') == 'is_live'
    )

def _is_shorts(url: str) -> bool:
    """Check if URL is YouTube Shorts"""
    return '/shorts/' in url.lower()

def _fallback_url_detection(url: str) -> str:
    """Fallback URL detection when yt-dlp fails"""
    url_lower = url.lower()

    if '/shorts/' in url_lower:
        return 'shorts'
    elif '/live/' in url_lower:
        return 'live'
    elif 'list=' in url_lower:
        return 'playlist'
    elif '/@' in url_lower or '/channel/' in url_lower or '/c/' in url_lower:
        return 'channel'
    else:
        return 'video'

def get_content_type(url: str) -> str:
    """Get content type of YouTube URL"""
    content_type, _ = get_url_info(url)
    return content_type

def validate_youtube_url(url: str) -> bool:
    """Validate if URL is a supported YouTube URL"""
    patterns = [
        r'^(https?://)?(www\.)?(youtube\.com|youtu\.be)/',
        r'^(https?://)?(www\.)?youtube\.com/watch\?v=',
        r'^(https?://)?(www\.)?youtube\.com/playlist\?list=',
        r'^(https?://)?(www\.)?youtube\.com/live/',
        r'^(https?://)?(www\.)?youtube\.com/shorts/',
        r'^(https?://)?(www\.)?youtu\.be/',
    ]

    return any(re.match(pattern, url, re.IGNORECASE) for pattern in patterns)