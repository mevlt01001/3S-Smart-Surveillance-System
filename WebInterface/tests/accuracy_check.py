#!/usr/bin/env python
"""
Smart Surveillance System accuracy measurement.

Plays labelled test videos to a private copy of the system as if they were cameras and
counts what it does with them: which incidents it catches, which it misses and how often
it raises an alarm on footage in which nothing happens.

    .conda/bin/python WebInterface/tests/accuracy_check.py
    .conda/bin/python WebInterface/tests/accuracy_check.py --only Test_Videos --parallel 4
    .conda/bin/python WebInterface/tests/accuracy_check.py --no-summaries --out /tmp/olcum

How it works. For every batch of videos it starts a private media server and a private
backend (own ports, temporary data directory; the running system and its data are not
touched), publishes each video once in real time as an RTSP camera and lets the unusual
movement detection run on it. While a video plays, the score of its camera is sampled; when
it ends, the events the system recorded are read from the journal. Nothing is mocked: the
numbers are those of the real pipeline (stream, model, thresholds, incident logic, summary).

The labels (accuracy_labels.json next to this file) say for every video whether an incident
is expected ("event") or not ("none"), optionally with the seconds in which it happens.

It needs the analysis server (Triton), ffmpeg and the MediaMTX binary of the camera
simulator. Thresholds and recording settings are taken from the running installation's
settings.json, so the result describes the system as it is configured. The score traces also
tell what other thresholds would have given (the table at the end of the report).
"""

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

import httpx

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LABELS_PATH = os.path.join(os.path.dirname(__file__), "accuracy_labels.json")
MEDIAMTX = os.path.join(PROJECT_ROOT, "Camera_System_Simulator", "bin", "mediamtx")
MEDIAMTX_CONFIG = os.path.join(PROJECT_ROOT, "Camera_System_Simulator", "config", "mediamtx_headless.yml")
PRODUCTION_SETTINGS = os.path.join(PROJECT_ROOT, "WebInterface", "backend", "settings.json")

PREROLL_SEC = 8.0        # the first frame is held this long so that the stream is connected when the video starts
SAMPLE_SEC = 0.25        # how often the score of every camera is read (the system scores about as often)
SETTLE_SEC = 6.0         # after a video ended: time for the incident to close and its clip to be written
SUMMARY_WAIT_SEC = 40.0  # ... and for the summaries that are still being written
WINDOW_SLACK_SEC = 3.0   # an event this close to the labelled seconds counts as that incident
SWEEP = (10, 20, 30, 40, 50, 60, 70, 80, 90)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def video_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    return float(out) if out else 0.0


# ------------------------------------------------------------------ processes
class MediaServer:
    """A private MediaMTX that only speaks RTSP over TCP on a free local port."""

    def __init__(self, work_dir):
        self.port = free_port()
        with open(MEDIAMTX_CONFIG, encoding="utf-8") as f:
            config = f.read()
        config = re.sub(r"(?m)^rtspAddress:.*$", f"rtspAddress: 127.0.0.1:{self.port}", config)
        config = re.sub(r"(?m)^rtspTransports:.*$", "rtspTransports: [tcp]", config)
        self.config_path = os.path.join(work_dir, "mediamtx.yml")
        with open(self.config_path, "w", encoding="utf-8") as f:
            f.write(config)
        self.log = open(os.path.join(work_dir, "mediamtx.log"), "ab")
        self.proc = subprocess.Popen([MEDIAMTX, self.config_path], cwd=work_dir, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.3).close()
                return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("the media server did not start")

    def url(self, name):
        return f"rtsp://127.0.0.1:{self.port}/{name}"

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


class Backend:
    """A private backend whose cameras are the given RTSP addresses."""

    def __init__(self, data_dir, cameras, summaries, settings_path):
        self.data_dir = data_dir
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        with open(os.path.join(data_dir, "cameras_db.json"), "w", encoding="utf-8") as f:
            json.dump({cam["id"]: cam for cam in cameras}, f)
        settings = {}
        if os.path.exists(settings_path):
            with open(settings_path, encoding="utf-8") as f:
                settings = json.load(f)
        settings.setdefault("anomaly", {})["continuous_pipeline"] = True  # the thing being measured
        with open(os.path.join(data_dir, "settings.json"), "w", encoding="utf-8") as f:
            json.dump(settings, f)

        env = dict(os.environ, AEGIS_DATA_DIR=data_dir, PYTHONPATH=PROJECT_ROOT + os.pathsep + os.environ.get("PYTHONPATH", ""))
        if not summaries:
            env["EVREN_API_KEY"] = ""
        self.log = open(os.path.join(data_dir, "server.log"), "ab")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "WebInterface.backend.server:app",
             "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning"],
            cwd=PROJECT_ROOT, env=env, stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.time() + 40
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("the backend exited during start-up, see " + os.path.join(data_dir, "server.log"))
            try:
                if httpx.get(self.base + "/api/health", timeout=1.0).status_code == 200:
                    return
            except Exception:
                time.sleep(0.2)
        raise RuntimeError("the backend did not become ready")

    def get(self, path, **params):
        return httpx.get(self.base + path, params=params, timeout=10).json()

    def stop(self):
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.log.close()


def publish(path, url):
    """
    Plays a video file once, in real time, to the RTSP address. The first frame is held for
    PREROLL_SEC first: the system needs a moment to connect, and an incident in the very
    first second of a video must not be lost to that.
    """
    return subprocess.Popen(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-an",
         "-vf", f"tpad=start_duration={PREROLL_SEC}:start_mode=clone,realtime",
         "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-pix_fmt", "yuv420p", "-g", "25",
         "-f", "rtsp", "-rtsp_transport", "tcp", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --------------------------------------------------------------------- one batch
def run_batch(videos, media, work_dir, summaries, settings_path):
    """Plays the videos of one batch side by side and returns their measurements."""
    cameras = [{"id": f"cam_{index}", "name": video["name"], "ip": "127.0.0.1", "port": 0,
                "stream_uri": media.url(f"v{index}"), "status": "online"} for index, video in enumerate(videos)]
    data_dir = tempfile.mkdtemp(prefix="batch_", dir=work_dir)
    backend = Backend(data_dir, cameras, summaries, settings_path)
    publishers = []
    try:
        started = time.time()
        publishers = [publish(video["path"], media.url(f"v{index}")) for index, video in enumerate(videos)]
        zero = started + PREROLL_SEC  # wall-clock time of second 0 of the videos
        traces = {camera["id"]: [] for camera in cameras}
        connected = {camera["id"]: None for camera in cameras}

        while any(process.poll() is None for process in publishers):
            time.sleep(SAMPLE_SEC)
            now = time.time()
            for state in backend.get("/api/live/state")["fleet"]["cameras"]:
                camera_id = state["camera_id"]
                if state.get("stream_live") and connected[camera_id] is None:
                    connected[camera_id] = round(now - zero, 1)
                if state.get("analyzed") and now >= zero:
                    traces[camera_id].append((round(now - zero, 1), float(state.get("score") or 0.0)))

        time.sleep(SETTLE_SEC)
        deadline = time.time() + (SUMMARY_WAIT_SEC if summaries else 0)
        journal = backend.get("/api/anomaly/journal", limit=1000)["journal"]
        while time.time() < deadline and any(entry.get("ai_status") == "generating" or entry.get("is_ongoing") for entry in journal):
            time.sleep(1.0)
            journal = backend.get("/api/anomaly/journal", limit=1000)["journal"]
        thresholds = backend.get("/api/live/state")["fleet"].get("thresholds", {})
    finally:
        for process in publishers:
            if process.poll() is None:
                process.kill()
        backend.stop()

    results = []
    for camera, video in zip(cameras, videos):
        events = sorted(
            ({"at": round(entry["timestamp"] - zero, 1), "lasted": entry.get("duration_sec") or 0.0,
              "score": entry.get("score"), "tier": entry.get("tier"),
              "verdict": entry.get("ai_verdict"), "headline": entry.get("ai_headline") if entry.get("ai_status") == "completed" else None}
             for entry in journal if entry.get("camera_id") == camera["id"]),
            key=lambda event: event["at"])
        trace = traces[camera["id"]]
        # The highest score reached: sampling can miss a short peak that an event has recorded
        peaks = [score for _, score in trace] + [float(event["score"] or 0) for event in events if event["at"] >= -1.0]
        results.append(dict(video, events=events, peak=max(peaks, default=None),
                            samples=len(trace), connected_at=connected[camera["id"]], trace=trace))
    return results, thresholds


# ----------------------------------------------------------------------- scoring
def judge(result):
    """Adds the verdict of one video: was the expected incident caught, how many alarms were false."""
    events = [event for event in result["events"] if event["at"] >= -1.0]  # during the held first frame: not the video
    window = result.get("window")
    if result["expect"] == "event":
        if window:
            inside = [event for event in events
                      if event["at"] <= window[1] + WINDOW_SLACK_SEC and event["at"] + event["lasted"] >= window[0] - WINDOW_SLACK_SEC]
        else:
            inside = events
        result["caught"] = bool(inside)
        result["false_alarms"] = len(events) - len(inside)
    elif result["expect"] == "none":
        result["caught"] = None
        result["false_alarms"] = len(events)
    else:  # not labelled yet: played and reported, but counted neither as a catch nor as a false alarm
        result["caught"] = None
        result["false_alarms"] = 0
    result["measured"] = result["samples"] > 0
    return result


def summarize(results, thresholds):
    measured = [result for result in results if result["measured"]]
    incidents = [result for result in measured if result["expect"] == "event"]
    quiet = [result for result in measured if result["expect"] == "none"]
    quiet_hours = sum(result["duration"] for result in quiet) / 3600.0
    events_true = [event for result in incidents for event in result["events"]]
    events_false = [event for result in quiet for event in result["events"]]

    def verdicts(events):
        judged = [event["verdict"] for event in events if event["verdict"]]
        return {name: judged.count(name) for name in ("confirmed", "normal", "unclear")} | {"judged": len(judged)}

    sweep = []
    for threshold in SWEEP:
        sweep.append({
            "threshold": threshold,
            "caught": sum(1 for result in incidents if (result["peak"] or 0) >= threshold),
            "incidents": len(incidents),
            "quiet_alarmed": sum(1 for result in quiet if (result["peak"] or 0) >= threshold),
            "quiet": len(quiet),
        })
    return {
        "thresholds": thresholds,
        "videos": len(results),
        "not_measured": [result["name"] for result in results if not result["measured"]],
        "incidents": len(incidents),
        "caught": sum(1 for result in incidents if result["caught"]),
        "missed": [result["name"] for result in incidents if not result["caught"]],
        "extra_alarms_in_incident_videos": sum(result["false_alarms"] for result in incidents),
        # One incident recorded as several events means the alarms are being split up
        "events_per_caught_incident": round(
            sum(len(result["events"]) for result in incidents if result["caught"])
            / max(1, sum(1 for result in incidents if result["caught"])), 1),
        "quiet_videos": len(quiet),
        "quiet_minutes": round(quiet_hours * 60, 1),
        "false_alarms": sum(result["false_alarms"] for result in quiet),
        "quiet_videos_with_alarm": sum(1 for result in quiet if result["false_alarms"]),
        "false_alarms_per_hour": round(sum(result["false_alarms"] for result in quiet) / quiet_hours, 1) if quiet_hours else None,
        "summary_on_real_incidents": verdicts(events_true),
        "summary_on_false_alarms": verdicts(events_false),
        "sweep": sweep,
    }


# ------------------------------------------------------------------------ report
def markdown(results, summary):
    lines = ["# Smart Surveillance System ölçüm raporu", "",
             f"Tarih: {time.strftime('%d.%m.%Y %H:%M')} · Eşikler: uyarı {summary['thresholds'].get('normal')}, "
             f"kritik {summary['thresholds'].get('warning')}", "", "## Özet", ""]
    if summary["incidents"]:
        lines.append(f"- **Olay içeren videolar:** {summary['incidents']} videonun {summary['caught']} tanesinde olay yakalandı"
                     f" (%{round(100 * summary['caught'] / summary['incidents'])}).")
        if summary["missed"]:
            lines.append(f"  - Kaçanlar: {', '.join(summary['missed'])}")
        if summary["events_per_caught_incident"] > 1.2:
            lines.append(f"  - Yakalanan olay başına ortalama **{summary['events_per_caught_incident']} ayrı kayıt** açıldı: "
                         "aynı olay parçalara bölünüyor (Ayarlar'daki olay birleştirme süresi kısa).")
    if summary["quiet_videos"]:
        lines.append(f"- **Olaysız videolar:** {summary['quiet_videos']} video, toplam {summary['quiet_minutes']} dakika; "
                     f"{summary['false_alarms']} yanlış alarm ({summary['quiet_videos_with_alarm']} videoda)"
                     + (f", saatte {summary['false_alarms_per_hour']}." if summary["false_alarms_per_hour"] is not None else "."))
    real, false = summary["summary_on_real_incidents"], summary["summary_on_false_alarms"]
    if real["judged"] or false["judged"]:
        lines.append(f"- **Özetin değerlendirmesi:** gerçek olayların {real['judged']} alarmından {real['confirmed']} tanesine “gerçek”, "
                     f"{real['normal']} tanesine “olağan” dedi; {false['judged']} yanlış alarmın {false['normal']} tanesine “olağan” dedi.")
    if summary["not_measured"]:
        lines.append(f"- **Ölçülemeyen videolar** (yayın bağlanmadı): {', '.join(summary['not_measured'])}")

    lines += ["", "## Başka eşiklerde ne olurdu", "",
              "Her videonun en yüksek skoruna göre: uyarı eşiği bu değer olsaydı kaç olay yakalanır, kaç olaysız video alarm verirdi.", "",
              "| Uyarı eşiği | Yakalanan olay | Alarm veren olaysız video |", "| ---: | ---: | ---: |"]
    lines += [f"| {row['threshold']} | {row['caught']} / {row['incidents']} | {row['quiet_alarmed']} / {row['quiet']} |" for row in summary["sweep"]]

    lines += ["", "## Videolar", "", "| Video | Beklenen | Sonuç | En yüksek skor | Alarmlar (saniye · skor · özet) |", "| --- | --- | --- | ---: | --- |"]
    for result in results:
        if not result["measured"]:
            outcome = "ölçülemedi"
        elif result["expect"] == "event":
            outcome = "yakalandı" if result["caught"] else "**kaçtı**"
        elif result["expect"] == "none":
            outcome = "temiz" if not result["false_alarms"] else f"**{result['false_alarms']} yanlış alarm**"
        else:
            outcome = f"etiketsiz ({len(result['events'])} alarm)"
        alarms = "; ".join(
            f"{event['at']:.0f} sn · {event['score']}" + (f" · {event['headline']}" if event["headline"] else "")
            + (f" ({event['verdict']})" if event["verdict"] else "") for event in result["events"]) or "—"
        expected = "olay" + (f" ({result['window'][0]}–{result['window'][1]} sn)" if result.get("window") else "") \
            if result["expect"] == "event" else "olay yok" if result["expect"] == "none" else "bilinmiyor"
        peak = "—" if result["peak"] is None else f"{result['peak']:.0f}"
        lines.append(f"| {result['name']} | {expected} | {outcome} | {peak} | {alarms} |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--labels", default=LABELS_PATH, help="label file (default: accuracy_labels.json next to this script)")
    parser.add_argument("--root", default=PROJECT_ROOT, help="directory the video paths of the labels are relative to")
    parser.add_argument("--settings", default=PRODUCTION_SETTINGS, help="settings.json whose thresholds are measured (default: the installation's)")
    parser.add_argument("--only", default="", help="measure only the videos whose path contains this text")
    parser.add_argument("--parallel", type=int, default=4, help="videos played at the same time (default 4)")
    parser.add_argument("--no-summaries", action="store_true", help="do not call the language model for incident summaries")
    parser.add_argument("--out", default=os.path.join(os.getcwd(), "accuracy_report"), help="directory for report.md and report.json")
    args = parser.parse_args()

    with open(args.labels, encoding="utf-8") as f:
        labels = json.load(f)["videos"]
    videos = []
    for label in labels:
        path = os.path.join(args.root, label["file"])
        if args.only and args.only not in label["file"]:
            continue
        if not os.path.exists(path):
            print(f"  atlandı (dosya yok): {label['file']}")
            continue
        videos.append(dict(label, path=path, name=label["file"].split("/", 1)[-1] if "/" in label["file"] else label["file"],
                           duration=round(video_duration(path), 1)))
    if not videos:
        print("Ölçülecek video yok.")
        return 1
    try:
        ready = httpx.get("http://localhost:8000/v2/health/ready", timeout=3).status_code == 200
    except Exception:
        ready = False
    if not ready:
        print("Analiz sunucusu (Triton) çalışmıyor; ölçüm yapılamaz.")
        return 1

    # Videos of similar length share a batch, so a batch lasts about as long as its videos
    videos.sort(key=lambda video: video["duration"])
    batches = [videos[index:index + args.parallel] for index in range(0, len(videos), args.parallel)]
    total = sum(max(video["duration"] for video in batch) + PREROLL_SEC + SETTLE_SEC + 8 for batch in batches)
    print(f"{len(videos)} video, {len(batches)} grup; yaklaşık {total / 60:.0f} dakika sürecek.")

    work_dir = tempfile.mkdtemp(prefix="aegis_accuracy_")
    media = MediaServer(work_dir)
    results, thresholds = [], {}
    try:
        for number, batch in enumerate(batches, 1):
            print(f"[{number}/{len(batches)}] " + ", ".join(video["name"] for video in batch), flush=True)
            batch_results, thresholds = run_batch(batch, media, work_dir, not args.no_summaries, args.settings)
            for result in batch_results:
                judge(result)
                state = ("ölçülemedi" if not result["measured"] else
                         ("yakalandı" if result["caught"] else "KAÇTI") if result["expect"] == "event" else
                         (f"{result['false_alarms']} yanlış alarm" if result["false_alarms"] else "temiz") if result["expect"] == "none" else
                         f"etiketsiz, {len(result['events'])} alarm")
                peak = "—" if result["peak"] is None else f"{result['peak']:.0f}"
                print(f"      {result['name']:<44} {state:<16} en yüksek skor {peak}", flush=True)
            results.extend(batch_results)
    finally:
        media.stop()
        shutil.rmtree(work_dir, ignore_errors=True)

    results.sort(key=lambda result: result["file"])
    summary = summarize(results, thresholds)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "videos": [{key: value for key, value in result.items() if key != "path"} for result in results]},
                  f, ensure_ascii=False, indent=1)
    report = markdown(results, summary)
    with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8") as f:
        f.write(report)
    print("\n" + report.split("## Videolar")[0])
    print(f"Ayrıntılı rapor: {os.path.join(args.out, 'report.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
