#!/usr/bin/env python3
"""
==============================================================================
AEGIS-PRO Headless NVR & CCTV Surveillance Simulator (CLI Master Engine)
==============================================================================
Features:
- Pure Headless CLI Engine (Zero Web/UI dependencies).
- Discovers video sets or any directory containing video files.
- Loops video endlessly (-stream_loop -1) to simulate continuous 24/7 CCTV feeds.
- Broadcasts real RFC 2326 compliant RTSP streams for all cameras simultaneously.
- Simultaneously records streams into segment files (e.g., 60-minute 1.mp4, 2.mp4...).
- Enforces a strict FIFO ring-buffer storage quota (e.g., 500 MB). Oldest segments
  are automatically purged when capacity is reached while new recordings continue.
- Zero-CPU re-encoding (-c:v copy) for ultra-fast, smooth performance.
- Clean real-time terminal telemetry dashboard.

Usage:
  python3 simulate_nvr.py --dir video_sets/set_1
  python3 simulate_nvr.py --dir video_sets/set_1 --segment-minutes 60 --quota-mb 500
  python3 simulate_nvr.py --dir video_sets/set_2 --segment-seconds 10 --quota-mb 50
==============================================================================
"""

import os
import sys
import time
import signal
import shutil
import logging
import argparse
import threading
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.onvif_service import HikvisionCameraServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("NVRSimulator")

BASE_DIR = Path(__file__).resolve().parent
MEDIAMTX_BIN = BASE_DIR / "bin" / "mediamtx"


class StorageManager:
    """Manages recording directory, tracks storage quota, and enforces FIFO purging."""

    def __init__(self, output_dir: Path, quota_mb: float):
        self.output_dir = output_dir.expanduser().resolve()
        self.quota_mb = float(quota_mb)
        self.lock = threading.Lock()
        self.total_purged_count = 0
        self.total_purged_bytes = 0

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            logger.error(f"Erişim Engellendi (Permission Denied): '{self.output_dir}' dizini oluşturulamıyor!")
            logger.error(f"İpucu: '/home/records' gibi sistem root dizinleri yerine kullanıcı ev dizininizi (~/records veya /home/{os.environ.get('USER', 'kullanici')}/records) ya da yerel bir dizini (./recordings) kullanın.")
            sys.exit(1)

    def get_storage_stats(self) -> Tuple[float, int, Dict[str, int]]:
        """Returns total MB used, total segment count, and per-camera segment counts."""
        total_bytes = 0
        total_files = 0
        cam_counts: Dict[str, int] = {}

        if not self.output_dir.exists():
            return 0.0, 0, {}

        for cam_dir in sorted(self.output_dir.iterdir()):
            if cam_dir.is_dir():
                count = 0
                for f in cam_dir.glob("*.mp4"):
                    try:
                        total_bytes += f.stat().st_size
                        count += 1
                    except OSError:
                        pass
                cam_counts[cam_dir.name] = count
                total_files += count

        used_mb = total_bytes / (1024 * 1024)
        return used_mb, total_files, cam_counts

    def purge_if_needed(self) -> int:
        """Purges oldest segments across all cameras down to 90% of quota if exceeded."""
        with self.lock:
            used_mb, _, _ = self.get_storage_stats()
            if used_mb <= self.quota_mb:
                return 0

            target_mb = self.quota_mb * 0.90
            candidate_files = []

            for cam_dir in self.output_dir.iterdir():
                if cam_dir.is_dir():
                    cam_files = []
                    for f in cam_dir.glob("*.mp4"):
                        try:
                            stat = f.stat()
                            cam_files.append((f, stat.st_mtime, stat.st_size))
                        except OSError:
                            pass
                    # Sort files per camera by modification time
                    cam_files.sort(key=lambda x: x[1])
                    # If camera has more than 1 segment, the newest one is actively being written;
                    # only older completed segments are candidates for FIFO purge.
                    if len(cam_files) > 1:
                        candidate_files.extend(cam_files[:-1])

            # Sort all candidate files globally ascending by modification time (oldest first)
            candidate_files.sort(key=lambda x: x[1])

            purged_count = 0
            current_mb = used_mb

            for file_path, _, size in candidate_files:
                try:
                    file_path.unlink()
                    purged_count += 1
                    self.total_purged_count += 1
                    self.total_purged_bytes += size
                    current_mb -= (size / (1024 * 1024))
                    if current_mb <= target_mb:
                        break
                except OSError:
                    pass

            return purged_count


class NVRSimulator:
    """Master NVR and CCTV Headless Simulator."""

    def __init__(
        self,
        input_dir: Path,
        segment_seconds: float,
        quota_mb: float,
        output_dir: Path,
        rtsp_port: int = 8554,
        naming_format: str = "sequential",
        base_onvif_port: int = 8891,
        onvif_user: str = "admin",
        onvif_pass: str = "admin123"
    ):
        self.input_dir = input_dir.expanduser().resolve()
        self.segment_seconds = segment_seconds
        self.quota_mb = quota_mb
        self.output_dir = output_dir.expanduser().resolve()
        self.rtsp_port = rtsp_port
        self.naming_format = naming_format
        self.base_onvif_port = base_onvif_port
        self.onvif_user = onvif_user
        self.onvif_pass = onvif_pass

        self.storage_mgr = StorageManager(self.output_dir, self.quota_mb)
        self.mediamtx_proc: Optional[subprocess.Popen] = None
        self.camera_procs: Dict[str, subprocess.Popen] = {}
        self.camera_files: List[Path] = []
        self.onvif_server: Optional[HikvisionCameraServer] = None
        self.is_running = False
        self.start_time = 0.0

    def discover_cameras(self) -> List[Path]:
        """Discovers video files in input directory, preferring .mp4 over .avi."""
        if not self.input_dir.exists() or not self.input_dir.is_dir():
            raise FileNotFoundError(f"Input directory does not exist: {self.input_dir}")

        all_files = list(self.input_dir.iterdir())
        stems = sorted(list(set(f.stem for f in all_files if f.suffix.lower() in [".avi", ".mp4"])))

        camera_files = []
        for s in stems:
            mp4_cand = self.input_dir / f"{s}.mp4"
            avi_cand = self.input_dir / f"{s}.avi"
            if mp4_cand.exists():
                camera_files.append(mp4_cand)
            elif avi_cand.exists():
                camera_files.append(avi_cand)

        if not camera_files:
            raise ValueError(f"No .mp4 or .avi video files found in {self.input_dir}")

        self.camera_files = camera_files
        return camera_files

    def start_rtsp_server(self):
        """Starts lightweight MediaMTX RTSP server if not already running."""
        # Check if port is already active
        try:
            check = subprocess.run(["ss", "-tulpn"], stdout=subprocess.PIPE, text=True)
            if f":{self.rtsp_port}" in check.stdout:
                logger.info(f"RTSP Server already listening on port {self.rtsp_port}.")
                return
        except Exception:
            pass

        if not MEDIAMTX_BIN.exists():
            raise FileNotFoundError(f"MediaMTX binary not found at {MEDIAMTX_BIN}")

        # Create temporary minimal config for RTSP server
        conf_path = BASE_DIR / "config" / "mediamtx_headless.yml"
        conf_content = f"""
api: no
metrics: no
pprof: no

rtsp: yes
rtspAddress: :{self.rtsp_port}
rtpAddress: :8556
rtcpAddress: :8557
rtspTransports: [tcp, udp, multicast]

webrtc: no
hls: no
rtmp: no
srt: no
moq: no

paths:
  all_others:
"""
        conf_path.parent.mkdir(parents=True, exist_ok=True)
        conf_path.write_text(conf_content.strip())

        logger.info(f"Starting MediaMTX RTSP Server on port {self.rtsp_port}...")
        self.mediamtx_proc = subprocess.Popen(
            [str(MEDIAMTX_BIN), str(conf_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid
        )
        time.sleep(0.8)

    def start_single_camera_stream(self, cam_file: Path):
        """Starts a single dual-output FFmpeg streaming process."""
        cam_name = cam_file.stem
        cam_dir = self.output_dir / cam_name
        cam_dir.mkdir(parents=True, exist_ok=True)

        rtsp_target = f"rtsp://127.0.0.1:{self.rtsp_port}/{cam_name}"

        if self.naming_format == "timestamp":
            seg_pattern = str(cam_dir / "%Y-%m-%d_%H-%M-%S.mp4")
            segment_args = [
                "-f", "segment",
                "-segment_time", str(self.segment_seconds),
                "-strftime", "1",
                "-reset_timestamps", "1",
                seg_pattern
            ]
        else:
            seg_pattern = str(cam_dir / "%d.mp4")
            segment_args = [
                "-f", "segment",
                "-segment_time", str(self.segment_seconds),
                "-segment_start_number", "1",
                "-reset_timestamps", "1",
                seg_pattern
            ]

        if cam_file.suffix.lower() == ".mp4":
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-stream_loop", "-1",
                "-re",
                "-i", str(cam_file),
                "-c:v", "copy",
                "-an",
                "-f", "rtsp",
                "-rtsp_transport", "tcp",
                rtsp_target,
                "-c:v", "copy",
                "-an",
                *segment_args
            ]
        else:
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-stream_loop", "-1",
                "-re",
                "-i", str(cam_file),
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-tune", "zerolatency",
                "-profile:v", "baseline",
                "-level", "3.1",
                "-pix_fmt", "yuv420p",
                "-b:v", "2000k",
                "-g", "5",
                "-an",
                "-f", "rtsp",
                "-rtsp_transport", "tcp",
                rtsp_target,
                "-c:v", "copy",
                "-an",
                *segment_args
            ]

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid
        )
        self.camera_procs[cam_name] = proc

    def start_camera_streams(self):
        """Starts continuous dual-output FFmpeg processes for all discovered cameras."""
        logger.info(f"Starting {len(self.camera_files)} camera streams with dual RTSP + segmented recording...")
        for cam_file in self.camera_files:
            self.start_single_camera_stream(cam_file)

    def check_and_restart_dead_processes(self):
        """Monitors and revives MediaMTX or camera FFmpeg streams if they crash."""
        if self.mediamtx_proc and self.mediamtx_proc.poll() is not None:
            self.start_mediamtx()

        for cam_file in self.camera_files:
            proc = self.camera_procs.get(cam_file.stem)
            if proc is None or proc.poll() is not None:
                self.start_single_camera_stream(cam_file)

    def render_dashboard(self):
        """Renders clean real-time status dashboard on the terminal."""
        used_mb, total_segs, cam_counts = self.storage_mgr.get_storage_stats()
        pct = min(100.0, (used_mb / self.quota_mb) * 100.0) if self.quota_mb > 0 else 0.0

        bar_len = 24
        filled = int((pct / 100.0) * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)

        uptime = int(time.time() - self.start_time)
        hrs = uptime // 3600
        mins = (uptime % 3600) // 60
        secs = uptime % 60
        uptime_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"

        sys.stdout.write("\033[2J\033[H") # Clear terminal and home cursor
        print("=" * 72)
        print(" 🛡️  AEGIS-PRO HEADLESS NVR & CCTV SURVEILLANCE SIMULATOR")
        print("=" * 72)
        print(f" ▶ Source Directory    : {self.input_dir.resolve()}")
        print(f" ▶ Cameras Streaming   : {len(self.camera_files)} Channels (Continuous Loop)")
        print(f" ▶ RTSP Server Port    : {self.rtsp_port} (TCP/RTP - RFC 2326)")
        print(f" ▶ Segment Duration    : {self.segment_seconds / 60:.1f} min ({self.segment_seconds:.1f}s)")
        print(f" ▶ Naming Convention   : {self.naming_format} (e.g., 1.mp4, 2.mp4...)")
        print(f" ▶ Storage Quota       : {self.quota_mb:.1f} MB (FIFO Ring-Buffer Active)")
        print(f" ▶ Storage Directory   : {self.output_dir.resolve()}")
        print(f" ▶ Simulator Uptime    : {uptime_str}")
        print("-" * 72)
        print(" ACTIVE HIKVISION CAMERAS (ONVIF Profile S/G/T + RTSP):")
        if self.onvif_server:
            for dev in self.onvif_server.devices:
                segs = cam_counts.get(dev.camera_id, 0)
                print(f"  ● {dev.camera_name:<20} -> ONVIF: http://{dev.host_ip}:{dev.onvif_port}/onvif/device_service [Diskte: {segs} parça]")
                print(f"    └─ RTSP: {dev.rtsp_url}")
        else:
            for cam_file in self.camera_files:
                cname = cam_file.stem
                segs = cam_counts.get(cname, 0)
                url = f"rtsp://127.0.0.1:{self.rtsp_port}/{cname}"
                print(f"  ● {cname:<12} -> {url:<36} [Diskte: {segs} parça]")
        print("-" * 72)
        print(f" DISK STORAGE CAPACITY (FIFO RING-BUFFER):")
        print(f"  [{bar}] {used_mb:.1f} MB / {self.quota_mb:.1f} MB ({pct:.1f}%)")
        print(f"  Toplam Segment Sayısı: {total_segs} adet | FIFO İle Silinen: {self.storage_mgr.total_purged_count} adet")
        print("=" * 72)
        print(" [Bilgi] Yayın, ONVIF ve kayıt kesintisiz devam ediyor. Çıkmak için Ctrl+C'ye basın.")
        sys.stdout.flush()

    def run(self):
        """Main execution loop."""
        self.is_running = True
        self.start_time = time.time()

        self.discover_cameras()
        self.start_rtsp_server()
        self.start_camera_streams()

        # Start Genuine Hikvision ONVIF Camera Fleet & WS-Discovery
        self.onvif_server = HikvisionCameraServer(
            camera_files=self.camera_files,
            rtsp_port=self.rtsp_port,
            base_onvif_port=self.base_onvif_port,
            username=self.onvif_user,
            password=self.onvif_pass
        )
        self.onvif_server.start()

        try:
            while self.is_running:
                # 1. Check storage quota and purge oldest if exceeded
                purged = self.storage_mgr.purge_if_needed()

                # Revive any dead camera streams or RTSP server
                self.check_and_restart_dead_processes()

                # 2. Render live terminal dashboard
                self.render_dashboard()

                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n🛑 Kullanıcı çıkış isteği alındı (SIGINT)...")
        finally:
            self.stop()

    def stop(self):
        """Terminates all FFmpeg camera processes, ONVIF servers, and MediaMTX server cleanly."""
        print("🛑 NVR Simülatörü kapatılıyor...")
        self.is_running = False

        if self.onvif_server:
            try:
                self.onvif_server.stop()
            except Exception:
                pass
            self.onvif_server = None

        for cam_name, proc in list(self.camera_procs.items()):
            try:
                if proc.poll() is None:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    proc.wait(timeout=1.0)
            except Exception:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
        self.camera_procs.clear()

        if self.mediamtx_proc:
            try:
                os.killpg(os.getpgid(self.mediamtx_proc.pid), signal.SIGTERM)
                self.mediamtx_proc.wait(timeout=1.0)
            except Exception:
                try:
                    os.killpg(os.getpgid(self.mediamtx_proc.pid), signal.SIGKILL)
                except Exception:
                    pass
            self.mediamtx_proc = None

        print("✅ Simülatör, ONVIF servisleri ve RTSP yayınları güvenli bir şekilde durduruldu.")


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="AEGIS-PRO Headless NVR & CCTV Surveillance Simulator (CLI Master Engine)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--dir", "-d",
        type=str,
        default="video_sets/set_1",
        help="Input directory containing video files (e.g. video_sets/set_1)"
    )
    parser.add_argument(
        "--segment-minutes", "-m",
        type=float,
        default=1.0,
        help="Segment duration in minutes for file splitting (e.g. 60 for 1-hour files)"
    )
    parser.add_argument(
        "--segment-seconds", "-s",
        type=float,
        default=None,
        help="Override segment duration in seconds (useful for fast testing, e.g. 10)"
    )
    parser.add_argument(
        "--quota-mb", "-q",
        type=float,
        default=100.0,
        help="Storage quota in MB before FIFO purge triggers"
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default="recordings",
        help="Base directory where segmented recordings will be saved"
    )
    parser.add_argument(
        "--rtsp-port", "-p",
        type=int,
        default=8554,
        help="RTSP server listening port"
    )
    parser.add_argument(
        "--naming", "-n",
        type=str,
        choices=["sequential", "timestamp"],
        default="timestamp",
        help="Segment file naming convention: 'sequential' (1.mp4, 2.mp4...) or 'timestamp' (YYYY-MM-DD_HH-MM-SS.mp4)"
    )
    parser.add_argument(
        "--onvif-base-port",
        type=int,
        default=8891,
        help="Base HTTP port for ONVIF device services (each camera gets an incremental port: 8891, 8892...)"
    )
    parser.add_argument(
        "--onvif-user",
        type=str,
        default="admin",
        help="ONVIF authentication username"
    )
    parser.add_argument(
        "--onvif-pass",
        type=str,
        default="admin123",
        help="ONVIF authentication password"
    )
    return parser.parse_args()


def main():
    args = parse_arguments()

    seg_seconds = args.segment_seconds if args.segment_seconds is not None else (args.segment_minutes * 60.0)

    sim = NVRSimulator(
        input_dir=Path(args.dir),
        segment_seconds=seg_seconds,
        quota_mb=args.quota_mb,
        output_dir=Path(args.output_dir),
        rtsp_port=args.rtsp_port,
        naming_format=args.naming,
        base_onvif_port=args.onvif_base_port,
        onvif_user=args.onvif_user,
        onvif_pass=args.onvif_pass
    )

    sim.run()


if __name__ == "__main__":
    main()
