DEFAULT_CONFIG = {
    'output_path': './downloads',
    'max_workers': 3,
    'batch_size': 10,
    'audio_only': False,
    'max_retries': 15,  # Increased for live streams
    'download_timeout': 7200,  # 2 hours for long live streams
    'format_preference': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
    'use_playlist_subdir': True,
    'enable_modern_features': True,  # Enable modern YouTube workarounds
    'live_stream_support': True,     # Support for live streams
    'enable_sponsorblock': False,    # SponsorBlock integration
    'cookies_file': None,           # Browser cookies for authentication
    'throttled_rate': None,         # Limit download speed
    'live_stream_wait': 30,         # Wait time for live streams
    'live_stream_max_wait': 120,    # Maximum wait time for live streams
    'use_cookies': True,            # Enable cookie-based authentication
    'browser_cookies': 'chrome',    # Browser to extract cookies from
    'retry_on_403': True,           # Retry on HTTP 403 errors
    'proxy_url': None,              # Proxy for geo-restricted content
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
    'retries': 15,  # Increased for live streams
    'fragment_retries': 15,
    'file_access_retries': 5,
    'skip_unavailable_fragments': True,
    'extract_flat': False,
    'ignoreerrors': True,
    'no_warnings': False,  # Show warnings for debugging
    'sleep_interval': 2,  # Sleep between requests
    'max_sleep_interval': 5,
}

# Live stream specific options
LIVE_STREAM_OPTS = {
    'live_from_start': False,
    'wait_for_video': (30, 120),  # (min_wait, max_wait)
    'retry_sleep_functions': {'http': lambda n: min(2 ** n, 300)},  # Exponential backoff
    'concurrent_fragment_downloads': 1,  # Avoid overwhelming servers
    'fragment_retries': 20,
    'skip_unavailable_fragments': True,
    'keep_fragments': False,
    'hls_use_mpegts': True,  # Better for live streams
}

# Cookie-based authentication options
COOKIE_OPTS = {
    'cookiesfrombrowser': ('chrome',),  # Extract cookies from Chrome
    'cookiefile': None,  # Will be set dynamically
}