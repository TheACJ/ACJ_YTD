"""Message queue utilities for inter-service communication"""

import json
import asyncio
from typing import Callable, Dict, Any, Optional, List
from datetime import datetime
import redis.asyncio as redis
from .models import ServiceMessage, MessageType

class MessageQueue:
    """Redis-based message queue for inter-service communication"""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis: Optional[redis.Redis] = None
        self.subscribers: Dict[MessageType, List[Callable]] = {}
        self._running = False

    async def connect(self) -> None:
        """Connect to Redis"""
        self.redis = redis.from_url(self.redis_url)
        await self.redis.ping()

    async def disconnect(self) -> None:
        """Disconnect from Redis"""
        if self.redis:
            await self.redis.close()

    async def publish(self, message: ServiceMessage) -> None:
        """Publish a message to the queue"""
        if not self.redis:
            await self.connect()

        channel = f"service:{message.message_type.value}"
        message_data = {
            "message_id": message.message_id,
            "message_type": message.message_type.value,
            "service": message.service,
            "timestamp": message.timestamp.isoformat(),
            "correlation_id": message.correlation_id,
            "payload": message.payload
        }

        await self.redis.publish(channel, json.dumps(message_data))

        # Also store in a persistent queue for reliability
        queue_key = f"queue:{message.message_type.value}"
        await self.redis.lpush(queue_key, json.dumps(message_data))

    async def subscribe(self, message_type: MessageType, callback: Callable[[ServiceMessage], None]) -> None:
        """Subscribe to a message type"""
        if message_type not in self.subscribers:
            self.subscribers[message_type] = []
        self.subscribers[message_type].append(callback)

    async def start_consuming(self) -> None:
        """Start consuming messages"""
        if not self.redis:
            await self.connect()

        self._running = True

        # Start consumers for each subscribed message type
        tasks = []
        for message_type in self.subscribers:
            task = asyncio.create_task(self._consume_messages(message_type))
            tasks.append(task)

        await asyncio.gather(*tasks, return_exceptions=True)

    async def stop_consuming(self) -> None:
        """Stop consuming messages"""
        self._running = False

    async def _consume_messages(self, message_type: MessageType) -> None:
        """Consume messages for a specific type"""
        if not self.redis:
            return

        pubsub = self.redis.pubsub()
        await pubsub.subscribe(f"service:{message_type.value}")

        try:
            while self._running:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message:
                    try:
                        data = json.loads(message['data'])
                        service_message = ServiceMessage(
                            message_id=data['message_id'],
                            message_type=MessageType(data['message_type']),
                            service=data['service'],
                            timestamp=datetime.fromisoformat(data['timestamp']),
                            correlation_id=data.get('correlation_id'),
                            payload=data.get('payload', {})
                        )

                        # Call all subscribers
                        for callback in self.subscribers[message_type]:
                            try:
                                await callback(service_message)
                            except Exception as e:
                                print(f"Error in message callback: {e}")

                    except Exception as e:
                        print(f"Error processing message: {e}")

        except Exception as e:
            print(f"Error in message consumer: {e}")
        finally:
            await pubsub.unsubscribe(f"service:{message_type.value}")

    async def get_pending_messages(self, message_type: MessageType, limit: int = 10) -> List[ServiceMessage]:
        """Get pending messages from persistent queue"""
        if not self.redis:
            await self.connect()

        queue_key = f"queue:{message_type.value}"
        messages = []

        for _ in range(limit):
            message_data = await self.redis.rpop(queue_key)
            if not message_data:
                break

            try:
                data = json.loads(message_data)
                message = ServiceMessage(
                    message_id=data['message_id'],
                    message_type=MessageType(data['message_type']),
                    service=data['service'],
                    timestamp=datetime.fromisoformat(data['timestamp']),
                    correlation_id=data.get('correlation_id'),
                    payload=data.get('payload', {})
                )
                messages.append(message)
            except Exception as e:
                print(f"Error parsing queued message: {e}")

        return messages

    async def queue_message(self, message: ServiceMessage) -> None:
        """Add message to persistent queue"""
        if not self.redis:
            await self.connect()

        queue_key = f"queue:{message.message_type.value}"
        message_data = {
            "message_id": message.message_id,
            "message_type": message.message_type.value,
            "service": message.service,
            "timestamp": message.timestamp.isoformat(),
            "correlation_id": message.correlation_id,
            "payload": message.payload
        }

        await self.redis.lpush(queue_key, json.dumps(message_data))

    async def get_queue_length(self, message_type: MessageType) -> int:
        """Get the length of a message queue"""
        if not self.redis:
            await self.connect()

        queue_key = f"queue:{message_type.value}"
        return await self.redis.llen(queue_key)

class MessageBus:
    """Central message bus for service communication"""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.queue = MessageQueue(redis_url)
        self.handlers: Dict[str, Callable] = {}

    async def start(self) -> None:
        """Start the message bus"""
        await self.queue.connect()

    async def stop(self) -> None:
        """Stop the message bus"""
        await self.queue.stop_consuming()
        await self.queue.disconnect()

    async def publish(self, message: ServiceMessage) -> None:
        """Publish a message"""
        await self.queue.publish(message)

    async def subscribe(self, message_type: MessageType, handler: Callable[[ServiceMessage], None]) -> None:
        """Subscribe to a message type"""
        await self.queue.subscribe(message_type, handler)

    async def start_consuming(self) -> None:
        """Start consuming messages"""
        await self.queue.start_consuming()

    def register_handler(self, message_type: str, handler: Callable) -> None:
        """Register a message handler"""
        self.handlers[message_type] = handler

    async def handle_message(self, message: ServiceMessage) -> None:
        """Handle an incoming message"""
        handler = self.handlers.get(message.message_type.value)
        if handler:
            await handler(message)
        else:
            print(f"No handler for message type: {message.message_type}")

# Global message bus instance
message_bus = MessageBus()