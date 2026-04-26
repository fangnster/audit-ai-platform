import json
import asyncio
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
import redis.asyncio as aioredis

from app.config import settings

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        # Maps case_id to a set of active WebSockets
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.redis: aioredis.Redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        self.pubsub = self.redis.pubsub()
        self.task = None

    async def connect(self, websocket: WebSocket, case_id: str):
        await websocket.accept()
        if case_id not in self.active_connections:
            self.active_connections[case_id] = set()
            # Subscribe to the Redis channel for this case
            if not self.task:
                self.task = asyncio.create_task(self._listen_redis())
            await self.pubsub.subscribe(f"case:{case_id}")
        self.active_connections[case_id].add(websocket)

    def disconnect(self, websocket: WebSocket, case_id: str):
        if case_id in self.active_connections:
            self.active_connections[case_id].discard(websocket)
            if not self.active_connections[case_id]:
                del self.active_connections[case_id]
                # Unsubscribe if no more connections for this case
                asyncio.create_task(self.pubsub.unsubscribe(f"case:{case_id}"))

    async def broadcast_to_case(self, case_id: str, message: dict):
        """Send message via Redis to all workers for this case."""
        await self.redis.publish(f"case:{case_id}", json.dumps(message))

    async def _listen_redis(self):
        """Listen for messages from Redis and route them to connected WebSockets."""
        try:
            async for message in self.pubsub.listen():
                if message["type"] == "message":
                    channel = message["channel"]
                    if channel.startswith("case:"):
                        case_id = channel.split(":")[1]
                        data = message["data"]
                        if case_id in self.active_connections:
                            dead_sockets = set()
                            for connection in self.active_connections[case_id]:
                                try:
                                    await connection.send_text(data)
                                except Exception:
                                    dead_sockets.add(connection)
                            for ds in dead_sockets:
                                self.disconnect(ds, case_id)
        except Exception as e:
            print(f"Redis pubsub error: {e}")

manager = ConnectionManager()

@router.websocket("/ws/cases/{case_id}")
async def websocket_case_endpoint(websocket: WebSocket, case_id: str):
    # Note: In a real production app, we would authenticate the websocket using a token
    # passed in the query string or initial frame.
    await manager.connect(websocket, case_id)
    try:
        while True:
            data = await websocket.receive_text()
            # E.g., user is typing, cursor position, etc.
            msg = json.loads(data)
            # Broadcast "user typing" or "lock section" events back to others
            # Adding sender_id so clients can ignore their own messages
            await manager.broadcast_to_case(case_id, msg)
    except WebSocketDisconnect:
        manager.disconnect(websocket, case_id)
