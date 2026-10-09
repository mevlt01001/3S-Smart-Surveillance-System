"""
AegisVision backend application.

Creates the FastAPI app, wires the API routers and the web interface, and makes sure the
process starts alone on its data directory and stops promptly.

Run with:  uvicorn WebInterface.backend.server:app
"""

import logging
import signal
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .paths import SHUTTING_DOWN, acquire_instance_lock

logging.basicConfig(level=logging.INFO, format="%(levelname)s:     [%(name)s] %(message)s")
for noisy in ("httpx", "httpx2"):  # one line per outgoing request would drown the log
    logging.getLogger(noisy).setLevel(logging.WARNING)

# One backend per data directory. This must happen before the services are imported:
# they load the JSON databases and start their worker threads at import time.
acquire_instance_lock()

from .anomaly_service import anomaly_service  # noqa: E402
from .api import routers  # noqa: E402
from .api.frontend import mount_frontend  # noqa: E402
from .camera_service import camera_service  # noqa: E402
from .live_detection_service import live_detection_service  # noqa: E402


class QuietPollingFilter(logging.Filter):
    """Keeps the access log readable: successful high-frequency polls of the interface are not logged."""

    NOISY_PATHS = ("/api/system/stats", "/api/anomaly/status", "/api/anomaly/stats", "/api/live/state", "/snapshot")

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        succeeded = " 200" in message or " 304" in message
        return not (succeeded and any(path in message for path in self.NOISY_PATHS))


logging.getLogger("uvicorn.access").addFilter(QuietPollingFilter())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """
    Prompt, clean shutdown. Browsers keep event streams and video sockets open indefinitely
    and the ASGI server waits for open connections before it exits; without a signal to
    those loops a stopped (or reloading) server lingered with its worker threads still
    writing to the databases. SIGINT / SIGTERM therefore set SHUTTING_DOWN first and then
    run the server's own handler.
    """

    def chain(previous):
        def handler(signum, frame):
            SHUTTING_DOWN.set()
            if callable(previous):
                previous(signum, frame)

        return handler

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, chain(signal.getsignal(sig)))
        except (ValueError, OSError):
            pass  # not the main thread (embedded / test runner): the code after `yield` still runs

    yield

    SHUTTING_DOWN.set()
    anomaly_service.running = False
    live_detection_service.running = False
    camera_service.shutdown()


app = FastAPI(title="AegisVision API", version="2.0.0", lifespan=lifespan)

# JSON, scripts and styles are compressed; JPEG frames, MP4 clips and event streams pass through
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

for router in routers:
    app.include_router(router)
mount_frontend(app)
