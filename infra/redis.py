import json
from typing import Any

import redis.asyncio as redis

from .settings import settings

redis_client = redis.from_url(settings.redis_url, decode_responses=True)


class RedisPubSub:
    def __init__(self, client: redis.Redis = redis_client):
        self.client = client

    async def publish(self, channel: str, data: Any) -> None:
        """Publish data to a Redis channel"""
        await self.client.publish(channel, json.dumps(data))

    async def subscribe(self, channel: str):
        """Subscribe to a Redis channel"""
        pubsub = self.client.pubsub()
        await pubsub.subscribe(channel)
        return pubsub

    async def get(self, key: str) -> str | None:
        """Get value from Redis"""
        return await self.client.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None) -> None:
        """Set value in Redis"""
        await self.client.set(key, json.dumps(value) if not isinstance(value, str) else value, ex=ex)

    async def close(self) -> None:
        """Close Redis connection"""
        await self.client.close()


pub_sub = RedisPubSub()