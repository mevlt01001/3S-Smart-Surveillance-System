"""
AegisVision backend package.

OpenCV reads its configuration from the environment when it is first imported, so it is
set here, before any module of the package can import it.
"""

import os

# Decoder chatter (damaged macroblocks, reconnect notices) would flood the terminal
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")
os.environ.setdefault("AV_LOG_FORCE_NOCOLOR", "1")
# Low-latency RTSP capture: without these the picture plays in slow motion and falls behind
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|framedrop;1|max_delay;500000|strict;experimental|loglevel;fatal",
)
