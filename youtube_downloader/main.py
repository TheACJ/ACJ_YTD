#!/usr/bin/env python3
import sys
import os
import signal
import threading
import time
from typing import Optional

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.config_manager import ConfigManager
from core.downloader import YouTubeDownloader
from core.url_handler import validate_youtube_url, get_content_type
from utils.helpers import parse_multiple_urls, print_download_summary
from utils.logger import setup_logger

logger = setup_logger(__name__)

# Global variables for graceful shutdown
shutdown_event = threading.Event()
active_downloader: Optional[YouTubeDownloader] = None
shutdown_in_progress = False

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global shutdown_in_progress

    if shutdown_in_progress:
        print("\n⚠️  Force shutdown requested. Exiting immediately...")
        # Force exit without cleanup
        os._exit(1)

    shutdown_in_progress = True
    print("\n🛑 Received shutdown signal. Initiating graceful shutdown...")

    # Set shutdown event to signal running operations
    shutdown_event.set()

    # Stop active downloader if it exists
    if active_downloader:
        print("⏹️  Stopping active downloads...")
        try:
            active_downloader.stop_all_downloads()
        except Exception as e:
            logger.error(f"Error stopping downloader: {e}")

    # Note: We don't exit here anymore - let the main thread handle cleanup
    # The main thread will detect the shutdown_event and exit gracefully

def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Termination signal

def main():
    """Main CLI entry point"""
    global active_downloader

    # Setup signal handlers for graceful shutdown
    setup_signal_handlers()

    # Check if shutdown was already requested (e.g., from previous signal)
    if shutdown_event.is_set():
        print("🛑 Shutdown already in progress. Exiting...")
        return

    config = ConfigManager()

    print("🎬 The ACJ's YouTube Multi-Content Downloader v5.0")
    print("🆕 ENHANCED: Microservices Architecture + Graceful Shutdown + Resume")
    print("=" * 70)
    print("💡 Tip: Press Ctrl+C at any time for graceful shutdown")
    print("=" * 70)

    # Get URLs from user
    urls_input = input("Enter YouTube URL(s): ").strip()

    if not urls_input:
        print("📝 Multi-line mode: Enter one URL per line (empty line to finish):")
        urls_list = []
        while True:
            line = input().strip()
            if not line:
                break
            urls_list.append(line)
        urls_input = '\n'.join(urls_list)

    if not urls_input:
        print("❌ No URLs provided. Exiting.")
        return

    urls = parse_multiple_urls(urls_input)

    if not urls:
        print("❌ No valid YouTube URLs found.")
        return

    # Validate URLs
    valid_urls = []
    for url in urls:
        if validate_youtube_url(url):
            valid_urls.append(url)
        else:
            print(f"⚠️  Skipping invalid URL: {url}")

    if not valid_urls:
        print("❌ No valid YouTube URLs to download.")
        return

    # Configuration
    output_dir = input(f"Output directory [default: {config.get('output_path')}]: ").strip()
    if output_dir:
        config.set('output_path', output_dir)

    audio_only = input("Download as MP3 audio only? (y/N): ").strip().lower() == 'y'
    if audio_only:
        config.set('audio_only', True)

    # Initialize downloader and track it globally for shutdown
    downloader = YouTubeDownloader(config)
    active_downloader = downloader

    # Download content
    print(f"\n🚀 Starting download of {len(valid_urls)} URL(s)...")
    print("💡 Press Ctrl+C to stop gracefully at any time")

    # Start download in a separate thread to keep main thread responsive
    from concurrent.futures import ThreadPoolExecutor, Future
    import time

    download_future: Optional[Future] = None

    def run_download():
        """Run download in separate thread"""
        try:
            return downloader.download_multiple_urls(valid_urls, audio_only)
        except Exception as e:
            logger.error(f"Download failed: {e}")
            raise

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            download_future = executor.submit(run_download)

            # Monitor the download while keeping main thread responsive
            while not download_future.done():
                if shutdown_event.is_set():
                    print("\n🛑 Shutdown requested. Cancelling download...")
                    download_future.cancel()
                    try:
                        # Wait a bit for cancellation
                        download_future.result(timeout=2.0)
                    except:
                        pass
                    break

                # Small sleep to prevent busy waiting
                time.sleep(0.1)

            # Get results if download completed
            if not download_future.cancelled():
                results = download_future.result()
                # Clear active downloader reference
                active_downloader = None
                # Print summary
                print_download_summary(results, config.get('output_path'))
            else:
                print("\n❌ Download was cancelled")
                active_downloader = None

    except Exception as e:
        # Clear active downloader reference on error
        active_downloader = None
        raise  # Re-raise to be handled by outer exception handler

    # Final check for shutdown signal
    if shutdown_event.is_set():
        print("\n🛑 Shutdown completed gracefully.")
        return

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Clear active downloader reference on error
        active_downloader = None

        logger.error(f"Unexpected error: {e}")
        print(f"❌ An unexpected error occurred: {e}")
        print("💡 Tip: Check the logs for more details")
        sys.exit(1)