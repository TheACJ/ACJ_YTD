"""Storage Service - Handles file storage, retrieval, and management"""

import os
import shutil
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse, StreamingResponse
import aiofiles
import uvicorn

# Import shared modules
import sys
sys.path.append('/app')
from shared.messaging import MessageBus
from shared.models import MessageType, create_storage_message

class StorageManager:
    """File storage manager"""

    def __init__(self, storage_path: str = "/app/storage"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.message_bus = MessageBus()
        self._init_cleanup_dirs()

    def _init_cleanup_dirs(self):
        """Initialize cleanup directories"""
        (self.storage_path / "temp").mkdir(exist_ok=True)
        (self.storage_path / "downloads").mkdir(exist_ok=True)
        (self.storage_path / "archive").mkdir(exist_ok=True)

    async def connect(self):
        """Connect to message bus"""
        await self.message_bus.start()

    async def disconnect(self):
        """Disconnect from message bus"""
        await self.message_bus.stop()

    async def store_file(self, file_path: Path, job_id: str = None, metadata: Dict[str, Any] = None) -> str:
        """Store a file in the storage system"""
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        # Generate storage path
        file_hash = self._calculate_file_hash(file_path)
        storage_dir = self.storage_path / "downloads" / file_hash[:2]
        storage_dir.mkdir(exist_ok=True)

        storage_path = storage_dir / f"{file_hash}_{file_path.name}"

        # Move file to storage
        shutil.move(str(file_path), str(storage_path))

        # Store metadata
        if metadata:
            metadata_path = storage_path.with_suffix('.meta.json')
            async with aiofiles.open(metadata_path, 'w') as f:
                await f.write(str(metadata).replace("'", '"'))

        # Publish storage event
        message = create_storage_message("upload", {
            "file_path": str(storage_path),
            "original_name": file_path.name,
            "file_hash": file_hash,
            "job_id": job_id,
            "metadata": metadata
        })
        await self.message_bus.publish(message)

        return str(storage_path)

    async def get_file_info(self, filename: str) -> Dict[str, Any]:
        """Get file information"""
        file_path = self._find_file(filename)
        if not file_path:
            raise HTTPException(status_code=404, detail="File not found")

        stat = file_path.stat()
        metadata = await self._get_file_metadata(file_path)

        return {
            "filename": file_path.name,
            "path": str(file_path),
            "size": stat.st_size,
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "metadata": metadata
        }

    async def list_files(self, path: str = "/") -> List[Dict[str, Any]]:
        """List files in a directory"""
        search_path = (self.storage_path / path.lstrip("/")).resolve()

        # Security check - ensure we're within storage directory
        if not str(search_path).startswith(str(self.storage_path)):
            raise HTTPException(status_code=403, detail="Access denied")

        if not search_path.exists():
            return []

        files = []
        for item in search_path.iterdir():
            if item.is_file() and not item.name.endswith('.meta.json'):
                stat = item.stat()
                metadata = await self._get_file_metadata(item)

                files.append({
                    "name": item.name,
                    "path": str(item.relative_to(self.storage_path)),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "is_download": item.parent.name == "downloads",
                    "metadata": metadata
                })

        return sorted(files, key=lambda x: x["modified"], reverse=True)

    async def delete_file(self, filename: str) -> bool:
        """Delete a file"""
        file_path = self._find_file(filename)
        if not file_path:
            return False

        # Delete file and metadata
        file_path.unlink()

        metadata_path = file_path.with_suffix('.meta.json')
        if metadata_path.exists():
            metadata_path.unlink()

        # Publish delete event
        message = create_storage_message("delete", {
            "file_path": str(file_path),
            "filename": filename
        })
        await self.message_bus.publish(message)

        return True

    async def cleanup_old_files(self, days: int = 30) -> int:
        """Clean up files older than specified days"""
        cutoff_time = datetime.now().timestamp() - (days * 24 * 60 * 60)
        deleted_count = 0

        for file_path in self.storage_path.rglob("*"):
            if file_path.is_file() and not file_path.name.endswith('.meta.json'):
                if file_path.stat().st_mtime < cutoff_time:
                    file_path.unlink()

                    # Delete metadata too
                    metadata_path = file_path.with_suffix('.meta.json')
                    if metadata_path.exists():
                        metadata_path.unlink()

                    deleted_count += 1

        # Publish cleanup event
        message = create_storage_message("cleanup", {
            "deleted_count": deleted_count,
            "days": days
        })
        await self.message_bus.publish(message)

        return deleted_count

    def _find_file(self, filename: str) -> Optional[Path]:
        """Find a file by name"""
        for file_path in self.storage_path.rglob(filename):
            if file_path.is_file() and not file_path.name.endswith('.meta.json'):
                return file_path
        return None

    def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate SHA256 hash of file"""
        hash_sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()

    async def _get_file_metadata(self, file_path: Path) -> Dict[str, Any]:
        """Get metadata for a file"""
        metadata_path = file_path.with_suffix('.meta.json')
        if metadata_path.exists():
            try:
                async with aiofiles.open(metadata_path, 'r') as f:
                    content = await f.read()
                    return eval(content)  # Simple eval for dict
            except:
                pass
        return {}

    async def get_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics"""
        total_size = 0
        file_count = 0

        for file_path in self.storage_path.rglob("*"):
            if file_path.is_file() and not file_path.name.endswith('.meta.json'):
                total_size += file_path.stat().st_size
                file_count += 1

        return {
            "total_files": file_count,
            "total_size_bytes": total_size,
            "storage_path": str(self.storage_path),
            "free_space": shutil.disk_usage(self.storage_path).free
        }

# Global storage manager
storage_manager = StorageManager()

# FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    await storage_manager.connect()
    yield
    await storage_manager.disconnect()

app = FastAPI(
    title="Storage Service",
    description="File storage and management service",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    stats = await storage_manager.get_storage_stats()
    return {
        "status": "healthy",
        "service": "storage-service",
        "storage_stats": stats,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/files")
async def list_files(path: str = Query("/", description="Directory path")):
    """List files in storage"""
    return await storage_manager.list_files(path)

@app.get("/files/info/{filename}")
async def get_file_info(filename: str):
    """Get file information"""
    return await storage_manager.get_file_info(filename)

@app.get("/files/download")
async def download_file(filename: str):
    """Download a file"""
    file_path = storage_manager._find_file(filename)
    if not file_path:
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type='application/octet-stream'
    )

@app.delete("/files/{filename}")
async def delete_file(filename: str):
    """Delete a file"""
    success = await storage_manager.delete_file(filename)
    if not success:
        raise HTTPException(status_code=404, detail="File not found")

    return {"message": "File deleted", "filename": filename}

@app.post("/files/upload")
async def upload_file(file: UploadFile = File(...), job_id: str = None):
    """Upload a file"""
    # Save to temp location first
    temp_path = storage_manager.storage_path / "temp" / file.filename
    temp_path.parent.mkdir(exist_ok=True)

    async with aiofiles.open(temp_path, 'wb') as f:
        content = await file.read()
        await f.write(content)

    # Move to permanent storage
    storage_path = await storage_manager.store_file(temp_path, job_id)

    return {
        "message": "File uploaded",
        "filename": file.filename,
        "storage_path": storage_path
    }

@app.post("/cleanup")
async def cleanup_files(days: int = Query(30, description="Delete files older than this many days")):
    """Clean up old files"""
    deleted_count = await storage_manager.cleanup_old_files(days)
    return {
        "message": f"Cleaned up {deleted_count} files",
        "days": days
    }

@app.get("/stats")
async def get_storage_stats():
    """Get storage statistics"""
    return await storage_manager.get_storage_stats()

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8003)),
        reload=False
    )