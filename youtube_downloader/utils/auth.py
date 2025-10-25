"""Authentication utilities for YouTube access"""

import os
import tempfile
from typing import Optional, Dict, Any
from pathlib import Path
import subprocess
import json

from utils.logger import setup_logger

logger = setup_logger(__name__)

class YouTubeAuthenticator:
    """Handle YouTube authentication via browser cookies"""

    SUPPORTED_BROWSERS = ['chrome', 'firefox', 'edge', 'safari']

    def __init__(self):
        self.temp_dir = Path(tempfile.gettempdir()) / 'ytd_cookies'

    def extract_cookies(self, browser: str = 'chrome') -> Optional[str]:
        """Extract cookies from browser and return cookie file path"""
        if browser not in self.SUPPORTED_BROWSERS:
            logger.error(f"Unsupported browser: {browser}")
            return None

        try:
            # Create temp directory for cookies
            self.temp_dir.mkdir(exist_ok=True)
            cookie_file = self.temp_dir / f'cookies_{browser}.txt'

            # Use yt-dlp's cookie extraction with better error handling
            import yt_dlp
            ydl_opts = {
                'cookiesfrombrowser': (browser,),
                'cookiefile': str(cookie_file),
                'quiet': True,
                'no_warnings': False,  # Show warnings for debugging
            }

            # First, try to extract cookies without testing
            try:
                # Just extract cookies, don't test yet
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    # This will create the cookie file
                    pass

                # Check if cookie file was created and has content
                if cookie_file.exists() and cookie_file.stat().st_size > 0:
                    logger.info(f"Successfully extracted cookies from {browser}")
                    return str(cookie_file)
                else:
                    logger.warning("Cookie file was not created or is empty")
                    return None

            except Exception as e:
                error_msg = str(e)
                if "DPAPI" in error_msg:
                    logger.error(f"DPAPI decryption failed. This is a Windows encryption issue.")
                    logger.error("Try running the application as Administrator or use a different browser.")
                    logger.error("Alternatively, you can manually export cookies from your browser.")
                    return None
                elif "keyring" in error_msg.lower():
                    logger.error("Keyring access failed. Try using a different browser or manual cookie export.")
                    return None
                else:
                    logger.warning(f"Cookie extraction failed: {error_msg}")
                    return None

        except Exception as e:
            logger.error(f"Failed to extract cookies from {browser}: {e}")
            return None

    def validate_cookies(self, cookie_file: str) -> bool:
        """Validate that cookies are working"""
        if not Path(cookie_file).exists():
            return False

        try:
            import yt_dlp
            ydl_opts = {
                'cookiefile': cookie_file,
                'quiet': True,
                'no_warnings': True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Try to access a simple public video first
                ydl.extract_info('https://www.youtube.com/watch?v=jNQXAC9IVRw', download=False)
                return True

        except Exception as e:
            logger.warning(f"Cookie validation failed: {e}")
            return False

    def convert_json_cookies_to_netscape(self, json_file: str) -> Optional[str]:
        """Convert Chrome JSON cookie export to Netscape format"""
        try:
            import json
            from pathlib import Path

            json_path = Path(json_file)
            if not json_path.exists():
                logger.error(f"JSON cookie file not found: {json_file}")
                return None

            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            cookies = data.get('cookies', [])
            if not cookies:
                logger.error("No cookies found in JSON file")
                return None

            # Create Netscape format cookie file
            netscape_file = json_path.parent / 'cookies_netscape.txt'

            with open(netscape_file, 'w', encoding='utf-8') as f:
                # Write Netscape header
                f.write("# Netscape HTTP Cookie File\n")
                f.write("# This file was generated from Chrome JSON export\n")
                f.write("# https://curl.se/docs/http-cookies.html\n")
                f.write("# This file can be used by wget, curl, yt-dlp, etc.\n\n")

                for cookie in cookies:
                    # Convert to Netscape format:
                    # domain, flag, path, secure, expiration, name, value
                    domain = cookie.get('domain', '')
                    flag = 'TRUE' if not cookie.get('hostOnly', False) else 'FALSE'
                    path = cookie.get('path', '/')
                    secure = 'TRUE' if cookie.get('secure', False) else 'FALSE'
                    expiration = str(int(cookie.get('expirationDate', 0)))
                    name = cookie.get('name', '')
                    value = cookie.get('value', '')

                    if name and value:  # Only write valid cookies
                        line = f"{domain}\t{flag}\t{path}\t{secure}\t{expiration}\t{name}\t{value}\n"
                        f.write(line)

            logger.info(f"Converted {len(cookies)} cookies to Netscape format: {netscape_file}")
            return str(netscape_file)

        except Exception as e:
            logger.error(f"Failed to convert JSON cookies: {e}")
            return None

    def create_manual_cookie_guide(self) -> str:
        """Create a guide for manual cookie extraction"""
        guide = """
MANUAL COOKIE EXTRACTION GUIDE:

For Chrome (JSON Export - RECOMMENDED):
1. Open Chrome and go to YouTube
2. Press F12 to open Developer Tools
3. Go to Application tab > Cookies > https://www.youtube.com
4. Right-click any cookie > Export as JSON
5. Save the file as 'www.youtube.com.json' in the project root
6. The system will automatically convert it to Netscape format

For Chrome (Manual Netscape):
1. Copy cookies from browser dev tools
2. Format as: domain\\tflag\\tpath\\tsecure\\texpiration\\tname\\tvalue
3. Save as 'cookies.txt' in the project root

For Firefox:
1. Install 'Export Cookies' extension
2. Export cookies as Netscape format
3. Save as 'cookies.txt' in the project root

The system automatically detects and uses available cookie files.
"""
        return guide

    def get_browser_profiles(self, browser: str) -> list:
        """Get available browser profiles"""
        profiles = []

        try:
            if browser == 'chrome':
                # Chrome profile detection
                chrome_path = self._get_chrome_path()
                if chrome_path and chrome_path.exists():
                    profiles.append('Default')
                    # Could extend to detect other profiles

            elif browser == 'firefox':
                # Firefox profile detection
                firefox_path = self._get_firefox_path()
                if firefox_path and firefox_path.exists():
                    profiles_dir = firefox_path / 'Profiles'
                    if profiles_dir.exists():
                        for profile_dir in profiles_dir.iterdir():
                            if profile_dir.is_dir() and profile_dir.name.endswith('.default'):
                                profiles.append(profile_dir.name)

        except Exception as e:
            logger.warning(f"Failed to detect browser profiles: {e}")

        return profiles

    def _get_chrome_path(self) -> Optional[Path]:
        """Get Chrome user data path"""
        import platform
        system = platform.system()

        if system == 'Windows':
            return Path(os.environ.get('LOCALAPPDATA', '')) / 'Google' / 'Chrome' / 'User Data'
        elif system == 'Darwin':  # macOS
            return Path.home() / 'Library' / 'Application Support' / 'Google' / 'Chrome'
        elif system == 'Linux':
            return Path.home() / '.config' / 'google-chrome'
        return None

    def _get_firefox_path(self) -> Optional[Path]:
        """Get Firefox profile path"""
        import platform
        system = platform.system()

        if system == 'Windows':
            return Path(os.environ.get('APPDATA', '')) / 'Mozilla' / 'Firefox'
        elif system == 'Darwin':  # macOS
            return Path.home() / 'Library' / 'Application Support' / 'Firefox'
        elif system == 'Linux':
            return Path.home() / '.mozilla' / 'firefox'
        return None

    def cleanup_temp_files(self):
        """Clean up temporary cookie files"""
        try:
            if self.temp_dir.exists():
                for cookie_file in self.temp_dir.glob('cookies_*.txt'):
                    cookie_file.unlink(missing_ok=True)
                self.temp_dir.rmdir()
        except Exception as e:
            logger.warning(f"Failed to cleanup temp files: {e}")

def setup_youtube_auth(config) -> Optional[str]:
    """Setup YouTube authentication and return cookie file path"""
    auth = YouTubeAuthenticator()

    try:
        browser = config.get('browser_cookies', 'chrome')

        # First try automatic extraction
        cookie_file = auth.extract_cookies(browser)

        if cookie_file and auth.validate_cookies(cookie_file):
            logger.info(f"YouTube authentication successful using {browser} cookies")
            return cookie_file

        # If automatic extraction fails, check for manual cookie file
        manual_cookie_file = config.get('cookies_file')
        if manual_cookie_file and Path(manual_cookie_file).exists():
            if auth.validate_cookies(manual_cookie_file):
                logger.info("Using manually provided cookie file")
                return manual_cookie_file

        # Check for JSON cookie export and convert it
        project_root = Path(__file__).parent.parent
        json_cookie_file = project_root / 'www.youtube.com.json'
        if json_cookie_file.exists():
            logger.info("Found Chrome JSON cookie export, converting to Netscape format...")
            netscape_file = auth.convert_json_cookies_to_netscape(str(json_cookie_file))
            if netscape_file and auth.validate_cookies(netscape_file):
                logger.info("Successfully converted and validated JSON cookies")
                return netscape_file

        # Check for cookies.txt in project root
        fallback_cookie_file = project_root / 'cookies.txt'
        if fallback_cookie_file.exists() and auth.validate_cookies(str(fallback_cookie_file)):
            logger.info("Using cookies.txt from project root")
            return str(fallback_cookie_file)

        # Check for converted Netscape file
        netscape_cookie_file = project_root / 'cookies_netscape.txt'
        if netscape_cookie_file.exists() and auth.validate_cookies(str(netscape_cookie_file)):
            logger.info("Using converted Netscape cookie file")
            return str(netscape_cookie_file)

        # If all methods fail, provide guidance
        logger.warning("YouTube authentication failed - proceeding without cookies")
        logger.info("To enable authentication, you can:")
        logger.info("1. Run the application as Administrator (for Windows DPAPI)")
        logger.info("2. Use a different browser")
        logger.info("3. Manually export cookies and save as 'cookies.txt'")
        logger.info("See the manual cookie extraction guide for details.")

        return None

    except Exception as e:
        logger.error(f"YouTube authentication setup failed: {e}")
        return None
    finally:
        # Don't cleanup immediately as cookies might be needed
        pass