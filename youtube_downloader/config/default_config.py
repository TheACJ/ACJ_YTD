DEFAULT_CONFIG = {
    'output_path': './downloads',
    'max_workers': 3,
    'batch_size': 10,
    'audio_only': False,
    'max_retries': 15,
    'download_timeout': 7200,
    'format_preference': 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
    'use_playlist_subdir': True,
    'enable_modern_features': True,
    'live_stream_support': True,
    'enable_sponsorblock': False,
    'cookies_file': None,
    'throttled_rate': None,
    'live_stream_wait': 30,
    'live_stream_max_wait': 120,
    'use_cookies': True,
    'browser_cookies': 'chrome',
    'retry_on_403': True,
    'proxy_url': None,
    'use_archive': False,
    'archive_file': '.youtube_archive.txt',
    # Restricted video bypass
    'bypass_geo_restriction': True,
    'age_gate_workaround': True,       # Use tv_embedded / android player clients
    'extractor_args': {
        'youtube': {
            'player_client': ['web', 'android', 'tv_embedded'],
            'player_skip': [],
        }
    },
    'impersonate': 'chrome',           # curl-cffi browser impersonation
}

# Modern yt-dlp options — updated for 2025 YouTube anti-bot measures
MODERN_YT_DLP_OPTS = {
    'http_headers': {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/124.0.0.0 Safari/537.36'
        ),
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    },
    'retries': 15,
    'fragment_retries': 20,
    'file_access_retries': 5,
    'skip_unavailable_fragments': True,
    'extract_flat': False,
    'ignoreerrors': True,
    'no_warnings': False,
    'sleep_interval': 1,
    'max_sleep_interval': 5,
    'sleep_interval_requests': 1,
    # Use multiple player clients to bypass restrictions/age gates
    'extractor_args': {
        'youtube': {
            'player_client': ['web', 'android', 'tv_embedded'],
            'player_skip': [],
        }
    },
    # Geo-bypass
    'geo_bypass': True,
    'geo_bypass_country': None,         # Set to 'US' if needed
}

# Live stream specific options
LIVE_STREAM_OPTS = {
    'live_from_start': False,
    'wait_for_video': (30, 120),
    'retry_sleep_functions': {'http': lambda n: min(2 ** n, 300)},
    'concurrent_fragment_downloads': 1,
    'fragment_retries': 20,
    'skip_unavailable_fragments': True,
    'keep_fragments': False,
    'hls_use_mpegts': True,
}

# Cookie-based authentication options
COOKIE_OPTS = {
    'cookiesfrombrowser': ('chrome',),
    'cookiefile': None,
}
