DEFAULT_CONFIG = {
    'output_path': './downloads',
    'max_workers': 3,
    'batch_size': 10,
    'audio_only': False,
    'max_retries': 10,  # Increased for reliability
    'download_timeout': 3600,
    'format_preference': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
    'use_playlist_subdir': True,
    'enable_modern_features': True,  # New: Enable modern YouTube workarounds
    'live_stream_support': True,     # New: Support for live streams
    'enable_sponsorblock': False,    # New: SponsorBlock integration
    'cookies_file': None,           # New: Browser cookies for authentication
    'throttled_rate': None,         # New: Limit download speed
}

# Modern yt-dlp options for current YouTube challenges
MODERN_YT_DLP_OPTS = {
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-us,en;q=0.5',
        'Accept-Encoding': 'gzip,deflate',
        'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
    },
    'retries': 10,
    'fragment_retries': 10,
    'file_access_retries': 3,
    'skip_unavailable_fragments': True,
    'extract_flat': False,
    'ignoreerrors': True,
}