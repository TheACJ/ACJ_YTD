#!/usr/bin/env python3
"""
ACJ YouTube Downloader v6.0
Rich terminal UI + restricted/age-gated video support
"""
import sys
import os
import signal
import threading
import time
from typing import Optional, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich import box
from rich.progress import (
    Progress, SpinnerColumn, BarColumn, TextColumn,
    DownloadColumn, TransferSpeedColumn, TimeRemainingColumn, TaskID
)
from rich.rule import Rule
from rich.align import Align
from rich.markup import escape

from config.config_manager import ConfigManager
from core.downloader import YouTubeDownloader
from core.url_handler import validate_youtube_url, get_content_type
from utils.helpers import parse_multiple_urls
from utils.logger import setup_logger

logger = setup_logger(__name__)
console = Console()

shutdown_event = threading.Event()
active_downloader: Optional[YouTubeDownloader] = None
shutdown_in_progress = False

ACJ_RED   = "#E63946"
ACJ_GOLD  = "#FFB703"
ACJ_CYAN  = "#00B4D8"
ACJ_GREEN = "#06D6A0"
ACJ_DIM   = "#6C757D"
ACJ_WHITE = "#F8F9FA"


def print_banner():
    t = Text()
    t.append("  ▄▄▄   ", style=f"bold {ACJ_RED}")
    t.append("ACJ", style=f"bold {ACJ_GOLD}")
    t.append(" YouTube Downloader", style=f"bold {ACJ_WHITE}")
    t.append("  v6.0\n", style=f"dim {ACJ_DIM}")
    t.append("  ─────────────────────────────────────────────\n", style=ACJ_DIM)
    t.append("  Supports: ", style=ACJ_DIM)
    t.append("Videos • Playlists • Channels • Live Streams\n", style=ACJ_CYAN)
    t.append("  Bypass:   ", style=ACJ_DIM)
    t.append("Age-gated • Geo-restricted • Auth-required\n", style=ACJ_GREEN)
    t.append("  Tip: ", style=ACJ_DIM)
    t.append("Ctrl+C", style=f"bold {ACJ_GOLD}")
    t.append(" for graceful shutdown at any time", style=ACJ_DIM)
    console.print(Panel(Align.center(t), border_style=ACJ_RED, padding=(1, 4), expand=True))

def print_section(title: str):
    console.print(Rule(f"[bold {ACJ_GOLD}]{title}[/]", style=ACJ_DIM))

def print_success(msg: str):
    console.print(f"  [bold {ACJ_GREEN}]✔[/]  {msg}")

def print_warning(msg: str):
    console.print(f"  [bold {ACJ_GOLD}]⚠[/]  {msg}")

def print_error(msg: str):
    console.print(f"  [bold {ACJ_RED}]✘[/]  {msg}")

def print_info(msg: str):
    console.print(f"  [dim {ACJ_CYAN}]ℹ[/]  [dim]{msg}[/dim]")


def collect_urls() -> List[str]:
    print_section("URLs")
    console.print(f"  [dim]Paste one or more YouTube URLs (comma / newline separated)[/dim]\n")
    raw = Prompt.ask(f"  [bold {ACJ_GOLD}]URL(s)[/]")

    if not raw.strip():
        console.print(f"\n  [dim]Multi-line mode — one URL per line, blank line to finish:[/dim]")
        lines: List[str] = []
        while True:
            line = Prompt.ask("  [dim]>[/dim]", default="")
            if not line.strip():
                break
            lines.append(line.strip())
        raw = "\n".join(lines)

    urls = parse_multiple_urls(raw)
    valid, invalid = [], []
    for u in urls:
        (valid if validate_youtube_url(u) else invalid).append(u)

    for u in invalid:
        print_warning(f"Skipped (not YouTube): [dim]{escape(u)}[/dim]")

    if not valid:
        print_error("No valid YouTube URLs found.")
        return []

    print_success(f"Found [bold]{len(valid)}[/bold] valid URL(s)")
    return valid


def collect_options(config: ConfigManager) -> bool:
    print_section("Options")
    default_out = config.get('output_path', './downloads')
    out = Prompt.ask(f"  [bold {ACJ_GOLD}]Output directory[/]", default=default_out)
    config.set('output_path', out)

    fmt_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    fmt_table.add_column(style=f"bold {ACJ_CYAN}")
    fmt_table.add_column(style=ACJ_DIM)
    fmt_table.add_row("1", "MP4 video (best quality ≤ 1080p)")
    fmt_table.add_row("2", "MP3 audio only")
    fmt_table.add_row("3", "Best available video (any res)")
    console.print(fmt_table)

    fmt_choice = Prompt.ask(f"  [bold {ACJ_GOLD}]Format[/]", choices=["1","2","3"], default="1")
    audio_only = fmt_choice == "2"
    if fmt_choice == "3":
        config.set('format_preference', 'bestvideo+bestaudio/best')
    return audio_only


def collect_auth(config: ConfigManager):
    print_section("Authentication  (for restricted / age-gated / private videos)")
    console.print(Panel(
        "[dim]yt-dlp pulls cookies directly from your browser — no manual export needed.\n"
        "Make sure you're logged into YouTube in that browser.\n\n"
        "[bold yellow]Windows tip:[/bold yellow] [dim]close the browser first for reliable cookie access.[/dim]\n"
        "If the browser is open and locked, the tool automatically retries WITHOUT\n"
        "cookies using the [bold]tv_embedded[/bold] player client (handles most age-gates).[/dim]",
        border_style=ACJ_DIM, padding=(0, 2),
    ))

    use_cookies = Confirm.ask(f"  [bold {ACJ_GOLD}]Extract cookies from browser?[/]", default=True)
    if use_cookies:
        browser = Prompt.ask(
            f"  [bold {ACJ_GOLD}]Browser[/]",
            choices=["chrome", "firefox", "edge", "brave", "opera"],
            default="chrome",
        )
        config.set('browser_cookies', browser)
        config.set('use_cookies', True)
        print_info(f"Will attempt cookies from {browser}  (auto-falls-back if locked)")
    else:
        manual = Prompt.ask(
            f"  [bold {ACJ_GOLD}]Path to cookies.txt (Netscape format), or blank to skip[/]",
            default="",
        )
        if manual:
            config.set('cookies_file', manual)
            config.set('use_cookies', True)
        else:
            config.set('use_cookies', False)
            print_warning("No cookies — restricted / age-gated videos may fail.")

    print_info("Age-gate & geo-restrictions: android + tv_embedded player clients active.")

    use_proxy = Confirm.ask(f"  [bold {ACJ_GOLD}]Use a proxy (geo-blocked content)?[/]", default=False)
    if use_proxy:
        proxy_url = Prompt.ask(f"  [bold {ACJ_GOLD}]Proxy URL[/] [dim](http://host:port)[/dim]")
        if proxy_url:
            config.set('proxy_url', proxy_url)
            print_success(f"Proxy set: {proxy_url}")


def make_progress() -> Progress:
    return Progress(
        SpinnerColumn(spinner_name="dots", style=f"bold {ACJ_CYAN}"),
        TextColumn("[bold][{task.fields[color]}]{task.description}[/{task.fields[color]}][/bold]"),
        BarColumn(bar_width=34, style=ACJ_DIM, complete_style=ACJ_CYAN, finished_style=ACJ_GREEN),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        TextColumn("[dim]{task.fields[status]}[/dim]"),
        console=console,
        transient=False,
    )


def build_ydl_progress_hook(progress: Progress, task_id: TaskID):
    """Return a yt-dlp progress hook that updates a Rich progress task."""
    def hook(d):
        status = d.get('status')
        if status == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            done  = d.get('downloaded_bytes', 0)
            speed = d.get('_speed_str', '').strip()
            progress.update(
                task_id,
                completed=done,
                total=total or None,
                status=speed,
                color=ACJ_CYAN,
            )
        elif status == 'finished':
            progress.update(task_id, status="[green]merging…[/green]", color=ACJ_GREEN)
        elif status == 'error':
            progress.update(task_id, status="[red]error[/red]", color=ACJ_RED)
    return hook


def print_summary(results: list, output_path: str):
    print_section("Download Summary")
    successful = [r for r in results if r.get('success')]
    failed     = [r for r in results if not r.get('success')]

    stats = Table(box=box.SIMPLE, show_header=False, padding=(0, 3))
    stats.add_column(style="bold")
    stats.add_column()
    stats.add_row(f"[{ACJ_GREEN}]✔ Successful[/]", str(len(successful)))
    stats.add_row(f"[{ACJ_RED}]✘ Failed[/]",       str(len(failed)))
    stats.add_row(f"[{ACJ_CYAN}]📁 Output[/]",     output_path)
    console.print(stats)

    if successful:
        t = Table(title="Completed", box=box.ROUNDED, border_style=ACJ_GREEN,
                  title_style=f"bold {ACJ_GREEN}", padding=(0,1))
        t.add_column("#",    style="dim",              width=4)
        t.add_column("Title",style=f"bold {ACJ_WHITE}",no_wrap=False, max_width=52)
        t.add_column("Type", style=ACJ_CYAN,           width=10)
        t.add_column("Info", style=ACJ_DIM,            width=14)
        for i, r in enumerate(successful, 1):
            title = escape(r.get('title', 'Unknown'))
            if r.get('type') == 'playlist':
                dl, tot = r.get('downloaded_entries',0), r.get('entry_count',0)
                t.add_row(str(i), title, "playlist", f"{dl}/{tot} videos")
            else:
                dur = int(r.get('duration', 0) or 0)
                h, rem = divmod(dur, 3600); m, s = divmod(rem, 60)
                dur_s = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
                kind  = "🔴 live" if r.get('is_live') else "video"
                t.add_row(str(i), title, kind, dur_s)
        console.print(t)

    if failed:
        t = Table(title="Failed", box=box.ROUNDED, border_style=ACJ_RED,
                  title_style=f"bold {ACJ_RED}", padding=(0,1))
        t.add_column("#",    style="dim", width=4)
        t.add_column("URL",  style=ACJ_DIM, no_wrap=False, max_width=44)
        t.add_column("Error",style=f"bold {ACJ_RED}", no_wrap=False, max_width=36)
        for i, r in enumerate(failed, 1):
            t.add_row(str(i), escape(r.get('url','')), escape(str(r.get('error',''))))
        console.print(t)

    console.print()
    console.print(Align.center(f"[bold {ACJ_GOLD}]🎉  Session complete![/]"))
    console.print()


def signal_handler(signum, frame):
    global shutdown_in_progress
    if shutdown_in_progress:
        console.print(f"\n[bold {ACJ_RED}]Force exit.[/]")
        os._exit(1)
    shutdown_in_progress = True
    console.print(f"\n[bold {ACJ_GOLD}]⚠  Shutdown signal — stopping gracefully…[/]")
    shutdown_event.set()
    if active_downloader:
        active_downloader.stop_all_downloads()


def main():
    global active_downloader

    signal.signal(signal.SIGINT,  signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    console.clear()
    print_banner()

    config = ConfigManager()

    valid_urls = collect_urls()
    if not valid_urls:
        return

    audio_only = collect_options(config)
    collect_auth(config)

    # ── Confirm ───────────────────────────────────────────────────────────────
    print_section("Ready")
    summary_tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    summary_tbl.add_column(style=f"bold {ACJ_GOLD}")
    summary_tbl.add_column(style=ACJ_WHITE)
    summary_tbl.add_row("URLs",   str(len(valid_urls)))
    summary_tbl.add_row("Format", "MP3 audio" if audio_only else "MP4 video")
    summary_tbl.add_row("Output", config.get('output_path'))
    auth_label = config.get('browser_cookies', 'none') if config.get('use_cookies') else "none"
    summary_tbl.add_row("Auth",   auth_label)
    console.print(summary_tbl)

    if not Confirm.ask(f"  [bold {ACJ_GOLD}]Start download?[/]", default=True):
        print_warning("Aborted.")
        return

    # ── Download ───────────────────────────────────────────────────────────────
    print_section("Downloading")
    downloader = YouTubeDownloader(config)
    active_downloader = downloader

    results = []

    with make_progress() as progress:
        tasks: dict = {}

        def rich_progress_hook_factory(url: str):
            # Re-use existing task on retry / cookie-fallback pass
            if url not in tasks:
                label = (f"{escape(url[:52])}…" if len(url) > 52 else escape(url))
                tasks[url] = progress.add_task(
                    description=f"[dim]{label}[/dim]",
                    total=None,
                    status="starting…",
                    color=ACJ_CYAN,
                )
            return build_ydl_progress_hook(progress, tasks[url])

        downloader._progress_hook_factory = rich_progress_hook_factory

        from concurrent.futures import ThreadPoolExecutor, as_completed

        def download_one(url):
            return downloader.download_single_item(url, audio_only)

        with ThreadPoolExecutor(max_workers=config.get('max_workers', 3)) as ex:
            futures = {ex.submit(download_one, u): u for u in valid_urls}
            for fut in as_completed(futures):
                url = futures[fut]
                if shutdown_event.is_set():
                    break
                try:
                    result = fut.result()
                    results.append(result)
                    tid = tasks.get(url)
                    if tid is not None:
                        ok    = result.get('success', False)
                        total = progress.tasks[tid].total or 1
                        progress.update(
                            tid,
                            completed=total, total=total,
                            description=(
                                f"[{ACJ_GREEN}]{escape(result.get('title','')[:50])}[/]"
                                if ok else f"[{ACJ_RED}]{escape(url[:50])}[/]"
                            ),
                            status="[green]done[/green]" if ok else "[red]failed[/red]",
                            color=ACJ_GREEN if ok else ACJ_RED,
                        )
                except Exception as e:
                    results.append({'success': False, 'url': url, 'error': str(e)})

    active_downloader = None
    print_summary(results, config.get('output_path'))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        console.print_exception()
        sys.exit(1)
