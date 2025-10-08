"""Analytics Service - Metrics collection and reporting"""

import asyncio
import json
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query
import redis.asyncio as redis
import uvicorn

# Import shared modules
import sys
sys.path.append('/app')
from shared.messaging import MessageBus
from shared.models import MessageType, AnalyticsEvent

class AnalyticsCollector:
    """Analytics data collector and processor"""

    def __init__(self, redis_url: str = "redis://redis:6379"):
        self.redis_url = redis_url
        self.redis: Optional[redis.Redis] = None
        self.message_bus = MessageBus(redis_url)
        self.metrics = {
            "total_downloads": 0,
            "successful_downloads": 0,
            "failed_downloads": 0,
            "total_bytes_downloaded": 0,
            "average_download_speed": 0.0,
            "average_download_time": 0.0,
            "active_users": 0,
            "peak_concurrent_downloads": 0
        }
        self.events: List[AnalyticsEvent] = []

    async def connect(self):
        """Connect to Redis and message bus"""
        self.redis = redis.from_url(self.redis_url)
        await self.redis.ping()
        await self.message_bus.start()

        # Subscribe to analytics events
        await self.message_bus.subscribe(MessageType.ANALYTICS_UPDATE, self._handle_analytics_event)

        # Load persisted metrics
        await self._load_metrics()

    async def disconnect(self):
        """Disconnect from services"""
        await self.message_bus.stop()
        if self.redis:
            await self.redis.close()

    async def _handle_analytics_event(self, message):
        """Handle analytics events"""
        event_data = message.payload
        event = AnalyticsEvent(
            event_type=event_data["event_type"],
            data=event_data["data"],
            timestamp=datetime.fromisoformat(message.timestamp)
        )

        self.events.append(event)
        await self._process_event(event)

        # Keep only recent events (last 1000)
        if len(self.events) > 1000:
            self.events = self.events[-1000:]

    async def _process_event(self, event: AnalyticsEvent):
        """Process an analytics event"""
        if event.event_type == "download_completed":
            self.metrics["total_downloads"] += 1
            self.metrics["successful_downloads"] += 1
            self.metrics["total_bytes_downloaded"] += event.data.get("file_size", 0)

            # Update averages
            download_time = event.data.get("download_time", 0)
            if download_time > 0:
                total_time = self.metrics["average_download_time"] * (self.metrics["successful_downloads"] - 1)
                self.metrics["average_download_time"] = (total_time + download_time) / self.metrics["successful_downloads"]

        elif event.event_type == "download_failed":
            self.metrics["total_downloads"] += 1
            self.metrics["failed_downloads"] += 1

        elif event.event_type == "job_created":
            self.metrics["active_users"] += 1

        # Persist metrics
        await self._save_metrics()

    async def _save_metrics(self):
        """Save metrics to Redis"""
        if not self.redis:
            return

        await self.redis.set("analytics:metrics", json.dumps(self.metrics))
        await self.redis.set("analytics:last_updated", datetime.now().isoformat())

    async def _load_metrics(self):
        """Load metrics from Redis"""
        if not self.redis:
            return

        metrics_data = await self.redis.get("analytics:metrics")
        if metrics_data:
            self.metrics.update(json.loads(metrics_data))

    async def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics"""
        # Add real-time calculations
        success_rate = 0.0
        if self.metrics["total_downloads"] > 0:
            success_rate = (self.metrics["successful_downloads"] / self.metrics["total_downloads"]) * 100

        return {
            **self.metrics,
            "success_rate": round(success_rate, 2),
            "last_updated": datetime.now().isoformat()
        }

    async def get_download_trends(self, hours: int = 24) -> Dict[str, Any]:
        """Get download trends over time"""
        cutoff_time = datetime.now() - timedelta(hours=hours)

        # Filter events by time
        recent_events = [e for e in self.events if e.timestamp > cutoff_time]

        # Group by hour
        hourly_stats = defaultdict(lambda: {"downloads": 0, "successful": 0, "failed": 0, "bytes": 0})

        for event in recent_events:
            hour_key = event.timestamp.strftime("%Y-%m-%d %H:00")
            if event.event_type == "download_completed":
                hourly_stats[hour_key]["downloads"] += 1
                hourly_stats[hour_key]["successful"] += 1
                hourly_stats[hour_key]["bytes"] += event.data.get("file_size", 0)
            elif event.event_type == "download_failed":
                hourly_stats[hour_key]["downloads"] += 1
                hourly_stats[hour_key]["failed"] += 1

        return {
            "period_hours": hours,
            "hourly_stats": dict(hourly_stats),
            "total_downloads": sum(stats["downloads"] for stats in hourly_stats.values()),
            "total_bytes": sum(stats["bytes"] for stats in hourly_stats.values())
        }

    async def get_popular_content(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most downloaded content"""
        content_stats = defaultdict(lambda: {"count": 0, "total_bytes": 0, "last_download": None})

        for event in self.events:
            if event.event_type == "download_completed":
                title = event.data.get("title", "Unknown")
                file_size = event.data.get("file_size", 0)

                content_stats[title]["count"] += 1
                content_stats[title]["total_bytes"] += file_size
                content_stats[title]["last_download"] = event.timestamp.isoformat()

        # Sort by download count
        sorted_content = sorted(
            content_stats.items(),
            key=lambda x: x[1]["count"],
            reverse=True
        )[:limit]

        return [
            {
                "title": title,
                "download_count": stats["count"],
                "total_bytes": stats["total_bytes"],
                "last_download": stats["last_download"]
            }
            for title, stats in sorted_content
        ]

    async def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics"""
        # Calculate performance metrics from events
        download_times = []
        download_speeds = []
        file_sizes = []

        for event in self.events[-1000:]:  # Last 1000 events
            if event.event_type == "download_completed":
                download_time = event.data.get("download_time")
                file_size = event.data.get("file_size", 0)

                if download_time and download_time > 0:
                    download_times.append(download_time)
                    if file_size > 0:
                        speed = file_size / download_time
                        download_speeds.append(speed)

                if file_size > 0:
                    file_sizes.append(file_size)

        return {
            "sample_size": len(download_times),
            "avg_download_time": sum(download_times) / len(download_times) if download_times else 0,
            "avg_download_speed": sum(download_speeds) / len(download_speeds) if download_speeds else 0,
            "avg_file_size": sum(file_sizes) / len(file_sizes) if file_sizes else 0,
            "min_download_time": min(download_times) if download_times else 0,
            "max_download_time": max(download_times) if download_times else 0,
            "total_events_analyzed": len(self.events)
        }

    async def generate_report(self, report_type: str, start_date: Optional[str] = None,
                            end_date: Optional[str] = None) -> Dict[str, Any]:
        """Generate various analytics reports"""
        # Parse dates
        start = datetime.fromisoformat(start_date) if start_date else datetime.now() - timedelta(days=7)
        end = datetime.fromisoformat(end_date) if end_date else datetime.now()

        # Filter events by date range
        filtered_events = [
            e for e in self.events
            if start <= e.timestamp <= end
        ]

        if report_type == "summary":
            return await self._generate_summary_report(filtered_events, start, end)
        elif report_type == "performance":
            return await self._generate_performance_report(filtered_events, start, end)
        elif report_type == "usage":
            return await self._generate_usage_report(filtered_events, start, end)
        else:
            return {"error": f"Unknown report type: {report_type}"}

    async def _generate_summary_report(self, events: List[AnalyticsEvent],
                                     start: datetime, end: datetime) -> Dict[str, Any]:
        """Generate summary report"""
        successful = sum(1 for e in events if e.event_type == "download_completed")
        failed = sum(1 for e in events if e.event_type == "download_failed")
        total_bytes = sum(e.data.get("file_size", 0) for e in events if e.event_type == "download_completed")

        return {
            "report_type": "summary",
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "total_downloads": successful + failed,
            "successful_downloads": successful,
            "failed_downloads": failed,
            "success_rate": (successful / (successful + failed)) * 100 if (successful + failed) > 0 else 0,
            "total_bytes_downloaded": total_bytes,
            "events_analyzed": len(events)
        }

    async def _generate_performance_report(self, events: List[AnalyticsEvent],
                                         start: datetime, end: datetime) -> Dict[str, Any]:
        """Generate performance report"""
        download_times = [
            e.data.get("download_time", 0)
            for e in events
            if e.event_type == "download_completed" and e.data.get("download_time", 0) > 0
        ]

        return {
            "report_type": "performance",
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "average_download_time": sum(download_times) / len(download_times) if download_times else 0,
            "min_download_time": min(download_times) if download_times else 0,
            "max_download_time": max(download_times) if download_times else 0,
            "total_downloads_analyzed": len(download_times)
        }

    async def _generate_usage_report(self, events: List[AnalyticsEvent],
                                   start: datetime, end: datetime) -> Dict[str, Any]:
        """Generate usage report"""
        # Group by day
        daily_stats = defaultdict(lambda: {"downloads": 0, "bytes": 0})

        for event in events:
            if event.event_type == "download_completed":
                day_key = event.timestamp.strftime("%Y-%m-%d")
                daily_stats[day_key]["downloads"] += 1
                daily_stats[day_key]["bytes"] += event.data.get("file_size", 0)

        return {
            "report_type": "usage",
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "daily_stats": dict(daily_stats),
            "total_days": len(daily_stats),
            "average_daily_downloads": sum(s["downloads"] for s in daily_stats.values()) / len(daily_stats) if daily_stats else 0
        }

# Global analytics collector
analytics_collector = AnalyticsCollector()

# FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    await analytics_collector.connect()
    yield
    await analytics_collector.disconnect()

app = FastAPI(
    title="Analytics Service",
    description="Metrics collection and analytics reporting",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "analytics-service",
        "events_collected": len(analytics_collector.events),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/metrics")
async def get_metrics():
    """Get current metrics"""
    return await analytics_collector.get_metrics()

@app.get("/trends")
async def get_download_trends(hours: int = Query(24, description="Hours to look back")):
    """Get download trends"""
    return await analytics_collector.get_download_trends(hours)

@app.get("/popular")
async def get_popular_content(limit: int = Query(10, description="Number of items to return")):
    """Get most popular content"""
    return await analytics_collector.get_popular_content(limit)

@app.get("/performance")
async def get_performance_stats():
    """Get performance statistics"""
    return await analytics_collector.get_performance_stats()

@app.get("/reports/{report_type}")
async def generate_report(
    report_type: str,
    start_date: Optional[str] = Query(None, description="Start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="End date (ISO format)")
):
    """Generate analytics reports"""
    return await analytics_collector.generate_report(report_type, start_date, end_date)

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8004)),
        reload=False
    )