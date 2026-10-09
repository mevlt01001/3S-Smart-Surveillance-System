"""
Live event feed: pushes new and changed incidents to every open page (server-sent events).

Publishers are worker threads, subscribers are HTTP handlers on the event loop. asyncio
queues are not thread-safe, so a published message is handed over on the subscriber's own loop.
"""

import asyncio
import json
import threading
from typing import Any, Dict, List, Tuple

QUEUE_SIZE = 256


class EventStream:
    def __init__(self):
        self._subscribers: List[Tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue:
        """Returns a queue of ready-to-send SSE messages. Call from the event loop."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        with self._lock:
            self._subscribers.append((asyncio.get_running_loop(), queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers = [item for item in self._subscribers if item[1] is not queue]

    def publish(self, event: Dict[str, Any]) -> None:
        """Sends an event to every subscriber. Safe to call from any thread."""
        message = f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        with self._lock:
            subscribers = list(self._subscribers)
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(self._deliver, queue, message)
            except RuntimeError:  # that loop is closed
                self.unsubscribe(queue)

    @staticmethod
    def _deliver(queue: asyncio.Queue, message: str) -> None:
        if queue.full():
            queue.get_nowait()  # a stalled client loses its oldest message instead of growing memory
        queue.put_nowait(message)


event_stream = EventStream()
