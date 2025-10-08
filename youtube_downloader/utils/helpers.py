import re
from typing import List, Dict
from urllib.parse import urlparse

def parse_multiple_urls(url_input: str) -> List[str]:
    """Parse multiple URLs from input string"""
    urls = []
    lines = url_input.strip().split('\n')

    for line in lines:
        line = line.strip()
        if line:
            # Split by common separators
            parts = re.split(r'[,\s]+', line)
            for part in parts:
                part = part.strip()
                if part and is_valid_url(part):
                    urls.append(part)

    return urls

def is_valid_url(url: str) -> bool:
    """Basic URL validation"""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def print_download_summary(results: List[Dict], output_path: str):
    """Print a summary of download results"""
    if not results:
        print("❌ No downloads to summarize.")
        return

    successful = [r for r in results if r.get('success', False)]
    failed = [r for r in results if not r.get('success', False)]

    print("\n" + "=" * 60)
    print("📊 DOWNLOAD SUMMARY")
    print("=" * 60)
    print(f"Total URLs processed: {len(results)}")
    print(f"✅ Successful downloads: {len(successful)}")
    print(f"❌ Failed downloads: {len(failed)}")
    print(f"📁 Output directory: {output_path}")
    print()

    if successful:
        print("✅ SUCCESSFUL DOWNLOADS:")
        for result in successful:
            title = result.get('title', 'Unknown')
            url = result.get('url', '')
            if result.get('type') == 'playlist':
                entry_count = result.get('entry_count', 0)
                downloaded = result.get('downloaded_entries', 0)
                print(f"  📂 {title} ({downloaded}/{entry_count} videos)")
            else:
                duration = result.get('duration', 0)
                duration_str = format_duration(duration) if duration else "Unknown"
                print(f"  🎬 {title} ({duration_str})")
        print()

    if failed:
        print("❌ FAILED DOWNLOADS:")
        for result in failed:
            url = result.get('url', '')
            error = result.get('error', 'Unknown error')
            print(f"  🔗 {url}")
            print(f"     Error: {error}")
        print()

    print("🎉 Download session completed!")

def format_duration(seconds: int) -> str:
    """Format duration in seconds to HH:MM:SS"""
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    else:
        return f"{minutes:02d}:{seconds:02d}"