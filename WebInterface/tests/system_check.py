#!/usr/bin/env python
"""
AegisVision end-to-end system check.

Starts a private backend instance (own port + temporary data directory, external LLM
calls disabled) and exercises the real HTTP / WebSocket / SSE surface. Nothing in the
production data directory is read or written.

    .conda/bin/python WebInterface/tests/system_check.py
    .conda/bin/python WebInterface/tests/system_check.py --sim-ip 192.168.1.100   # with live cameras

Checks that need live video (stream delivery, signal-loss handling, change detection...)
run only when the camera simulator is reachable; they are reported as SKIPPED otherwise.
Exit code is 0 only if every executed check passed.
"""

import argparse
import asyncio
import json
import os
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import time

import httpx

try:
    import websockets
except ImportError:  # pragma: no cover
    websockets = None

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RESULTS = []  # (status, name, detail)


def record(status, name, detail=""):
    RESULTS.append((status, name, detail))
    icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "–"}[status]
    print(f"  {icon} {name}" + (f"  [{detail}]" if detail else ""), flush=True)


def check(name, condition, detail=""):
    record("PASS" if condition else "FAIL", name, detail)
    return bool(condition)


def skip(name, why):
    record("SKIP", name, why)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_open(host, port, timeout=0.5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def proc_cpu_seconds(pid):
    with open(f"/proc/{pid}/stat") as f:
        parts = f.read().rsplit(")", 1)[1].split()
    return (int(parts[11]) + int(parts[12])) / os.sysconf("SC_CLK_TCK")


def proc_rss_mb(pid):
    with open(f"/proc/{pid}/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024.0
    return 0.0


class Server:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.proc = None
        self.log_path = os.path.join(data_dir, "server.log")

    def start(self):
        env = dict(os.environ)
        env["AEGIS_DATA_DIR"] = self.data_dir
        env["AEGIS_LOCK_WAIT_SEC"] = "15"
        env["EVREN_API_KEY"] = ""  # never call the external LLM / VLM from tests
        env["PYTHONPATH"] = PROJECT_ROOT + os.pathsep + env.get("PYTHONPATH", "")
        self.log = open(self.log_path, "ab")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "WebInterface.backend.server:app",
             "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning"],
            cwd=PROJECT_ROOT, env=env, stdout=self.log, stderr=subprocess.STDOUT,
        )
        t0 = time.time()
        while time.time() - t0 < 40:
            if self.proc.poll() is not None:
                raise RuntimeError("server exited during start-up, see " + self.log_path)
            try:
                if httpx.get(self.base + "/api/health", timeout=1.0).status_code == 200:
                    return time.time() - t0
            except Exception:
                time.sleep(0.2)
        raise RuntimeError("server did not become ready")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.send_signal(signal.SIGINT)
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if getattr(self, "log", None):
            self.log.close()

    @property
    def pid(self):
        return self.proc.pid


def wait_until(fn, timeout=20.0, interval=0.3):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            last = fn()
            if last:
                return last
        except Exception as e:  # noqa
            last = None
        time.sleep(interval)
    return last


# ----------------------------------------------------------------------------- checks
def test_static_and_health(c, srv, startup_sec):
    print("\n[1] Start-up, static assets, health")
    check("server starts and answers /api/health", True, f"{startup_sec:.1f}s to ready")
    rss = proc_rss_mb(srv.pid)
    check("backend does not load torch (RSS at start < 300 MB)", rss < 300, f"{rss:.0f} MB")
    r = c.get("/")
    check("index.html is served", r.status_code == 200 and "AegisVision" in r.text)
    check("index is always revalidated (Cache-Control: no-cache)", r.headers.get("cache-control") == "no-cache")
    r = c.get("/ui/js/events.js", headers={"Accept-Encoding": "gzip"})
    check("static JS is gzip-compressed", r.headers.get("content-encoding") == "gzip")
    check("static JS is always revalidated (Cache-Control: no-cache)", r.headers.get("cache-control") == "no-cache")
    import re
    html = c.get("/").text
    assets = sorted(set(re.findall(r'(/ui/[^"\'?]+)', html)))
    missing = [a for a in assets if c.get(a).status_code != 200]
    check(f"all {len(assets)} assets referenced by index.html exist", bool(assets) and not missing, ", ".join(missing))

    # A browser that used an earlier version may still hold its /static files (they were served
    # without cache headers). The current page must be unable to pick any of them up.
    check("index.html references nothing under the legacy /static address", "/static/" not in html)
    modules = [a for a in assets if a.endswith(".js")]
    seen, queue, escaping = set(modules), list(modules), []
    while queue:
        url = queue.pop()
        for spec in re.findall(r'(?:from|import)\s*\(?\s*["\']([^"\']+\.js[^"\']*)["\']', c.get(url).text):
            if not spec.startswith("./"):
                escaping.append(f"{url} -> {spec}")
                continue
            dep = url.rsplit("/", 1)[0] + "/" + spec[2:].split("?")[0]
            if dep not in seen:
                seen.add(dep)
                queue.append(dep)
    check(f"all {len(seen)} script modules resolve inside /ui (no import can hit an old cached file)",
          not escaping and all(u.startswith("/ui/") for u in seen), "; ".join(escaping))
    r = c.get("/static/js/home.js")
    check("a cached page of the previous version is handed over to the current interface",
          r.status_code == 200 and "location.reload()" in r.text and "export const initHomeModule" in r.text
          and r.headers.get("cache-control") == "no-store", r.text[:80])
    check("the legacy address serves nothing but that stand-in script",
          c.get("/static/css/theme.css").status_code == 404 and c.get("/static/js/..%2Fserver.py").status_code == 404)
    ids = re.findall(r'\bid="([^"]+)"', html)
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    check("index.html has no duplicate element ids", not duplicates, ", ".join(duplicates))
    used = set()
    for url in sorted(seen):
        used.update(re.findall(r'\$\("#([\w-]+)"', c.get(url).text))
    unknown = sorted(used - set(ids))
    check(f"every element the scripts look up by id exists in index.html ({len(used)} ids)", not unknown, ", ".join(unknown))
    stats = c.get("/api/system/stats").json()
    check("telemetry reports no invented latency before any inference ran",
          stats["triton"]["object_detection_latency_ms"] is None, json.dumps(stats["triton"]["status"]))


def test_idle_cpu(srv):
    print("\n[2] Idle behaviour (no cameras, no clients)")
    c0 = proc_cpu_seconds(srv.pid)
    time.sleep(4.0)
    cpu = (proc_cpu_seconds(srv.pid) - c0) / 4.0 * 100
    check("no background thread busy-spins when idle (< 10% of one core)", cpu < 10.0, f"{cpu:.1f}%")


def test_settings(c):
    print("\n[3] Settings validation")
    r = c.post("/api/settings", json={"anomaly": {"threshold_normal": 80, "threshold_warning": 20, "batch_size": 999,
                                                  "triton_url": "http://localhost:8000/"},
                                      "recording": {"max_storage_mb": -5, "padding_sec": "abc"},
                                      "live_wall": {"default_layout": "grid-9x9"}})
    s = r.json()["settings"]
    check("critical threshold is forced above the warning threshold",
          s["anomaly"]["threshold_warning"] > s["anomaly"]["threshold_normal"],
          f"{s['anomaly']['threshold_normal']}/{s['anomaly']['threshold_warning']}")
    check("batch size is clamped to 1..8", 1 <= s["anomaly"]["batch_size"] <= 8, str(s["anomaly"]["batch_size"]))
    check("triton url is normalised to host:port", s["anomaly"]["triton_url"] == "localhost:8000", s["anomaly"]["triton_url"])
    check("garbage numbers fall back to sane values",
          s["recording"]["max_storage_mb"] >= 50 and isinstance(s["recording"]["padding_sec"], (int, float)))
    check("unknown layout is rejected", s["live_wall"]["default_layout"] in ("grid-1x1", "grid-2x2", "grid-3x2", "grid-4x3"))
    r = c.post("/api/settings", content=b"[1,2,3]", headers={"Content-Type": "application/json"})
    check("non-object settings payload is rejected (422)", r.status_code == 422, str(r.status_code))
    r = c.post("/api/settings/reset")
    d = r.json()["settings"]["anomaly"]
    check("reset restores defaults", (d["threshold_normal"], d["threshold_warning"]) == (25, 50))
    fleet = c.get("/api/anomaly/status").json()
    check("fleet summary exposes the configured thresholds", fleet.get("thresholds") == {"normal": 25.0, "warning": 50.0},
          json.dumps(fleet.get("thresholds")))


def test_camera_validation(c):
    print("\n[4] Camera registration: validation and unreachable device")
    check("invalid IP is rejected (422)", c.post("/api/cameras/add", json={"ip": "999.1.1.1", "port": 80}).status_code == 422)
    check("hostname/garbage IP is rejected (422)", c.post("/api/cameras/add", json={"ip": "<script>", "port": 80}).status_code == 422)
    check("port out of range is rejected (422)", c.post("/api/cameras/add", json={"ip": "127.0.0.1", "port": 70000}).status_code == 422)
    check("unknown camera snapshot returns a placeholder JPEG, not an error",
          c.get("/api/cameras/nope/snapshot").content[:2] == b"\xff\xd8")
    check("deleting an unknown camera is 404", c.delete("/api/cameras/nope").status_code == 404)
    check("updating an unknown camera is 404", c.put("/api/cameras/nope", json={"name": "x"}).status_code == 404)

    dead_port = free_port()
    r = c.post("/api/cameras/add", json={"ip": "127.0.0.1", "port": dead_port, "username": "admin",
                                         "password": "s3cret-pw", "name": "Ölü <b>Kamera</b>", "rtsp_port": free_port()},
               timeout=40)
    cam = r.json().get("camera", {})
    check("unreachable camera is stored but reported offline", r.status_code == 200 and cam.get("status") == "offline",
          cam.get("status_message", ""))
    check("API never returns the stored camera password", "password" not in cam and "s3cret-pw" not in
          json.dumps({k: v for k, v in cam.items() if k != "stream_uri"}))
    cid = cam["id"]
    listing = c.get("/api/cameras").json()["cameras"]
    entry = next(x for x in listing if x["id"] == cid)
    check("camera list carries live stream health",
          entry.get("stream_live") is False and "stream_fps" in entry and "stream_standby" in entry and "stream_connecting" in entry)
    time.sleep(1.5)
    fleet = {x["camera_id"]: x for x in c.get("/api/anomaly/status").json()["cameras"]}
    check("a camera without video is not counted as 'Normal / Güvenli'", fleet[cid]["tier"] == "offline",
          f"tier={fleet[cid]['tier']} label={fleet[cid]['label']}")
    snap = c.get(f"/api/cameras/{cid}/snapshot")
    check("dead camera snapshot is a placeholder JPEG", snap.status_code == 200 and snap.content[:2] == b"\xff\xd8")
    return cid


def test_rules(c, dead_cam_id):
    print("\n[5] Rules API")
    zone = {"id": "zone_t1", "name": "Acil Çıkış", "description": "", "zone_type": "change_detection",
            "points": [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}, {"x": 0.1, "y": 0.9}]}
    check("camera rule without a camera is rejected (422)",
          c.post("/api/rules", json={"title": "x", "scope": "camera", "zones": [zone]}).status_code == 422)
    check("rule with an empty title is rejected (422)",
          c.post("/api/rules", json={"title": "  ", "scope": "system"}).status_code == 422)
    r = c.post("/api/rules", json={"title": "Acil Çıkış Kontrolü", "scope": "camera", "camera_id": dead_cam_id,
                                   "camera_name": "Ölü Kamera", "zones": [zone]})
    rule = r.json().get("rule", {})
    check("change-detection rule is created", r.status_code == 200 and rule.get("id"))
    check("change-detection rule needs no LLM compilation", rule.get("compile_status") == "not_required", str(rule.get("compile_status")))
    rid = rule["id"]

    det_zone = dict(zone, id="zone_t2", name="Depo", description="Bu alanda insan varsa alarm ver", zone_type="detection")
    r2 = c.post("/api/rules", json={"title": "Depo", "scope": "camera", "camera_id": dead_cam_id, "zones": [det_zone]})
    rule2 = r2.json()["rule"]
    check("without LLM access a detection rule is reported as not compiled (never silently 'active')",
          rule2["compile_status"] in ("unavailable", "compiling", "fallback", "compiled"), rule2["compile_status"])

    # -- a rule defined by choices from lists needs no language model, and working hours
    chosen = dict(zone, id="zone_t3", name="Koridor", description="", zone_type="detection",
                  manual={"subject": "person", "condition": "waiting", "value": 20})
    r3 = c.post("/api/rules", json={"title": "Bekleme", "scope": "camera", "camera_id": dead_cam_id, "zones": [chosen],
                                    "schedule": {"start": "22:00", "end": "06:00", "days": [0, 1, 2, 3, 4]}})
    rule3 = r3.json().get("rule", {})
    summary3 = (rule3.get("zones") or [{}])[0].get("plan_summary") or {}
    check("a rule chosen from lists is ready at once, without the language model",
          r3.status_code == 200 and rule3.get("compile_status") == "compiled"
          and summary3.get("text") == "Kişi bölgede 20 saniyeden uzun kalınca", f"{rule3.get('compile_status')} / {summary3.get('text')}")
    check("working hours are stored and described",
          rule3.get("schedule", {}).get("source") == "user" and rule3.get("schedule_text") == "22:00–06:00 · Hafta içi"
          and isinstance(rule3.get("active_now"), bool), f"{rule3.get('schedule')} / {rule3.get('schedule_text')}")
    cleared = c.put(f"/api/rules/{rule3['id']}", json={"schedule": {}}).json()["rule"]
    check("working hours can be set back to 'always'", cleared["schedule_text"] == "" and cleared["active_now"] is True, str(cleared.get("schedule")))
    incomplete = dict(chosen, id="zone_t4", manual={"subject": "person", "condition": "more_than", "value": None})
    check("a list rule without its number is rejected (422)",
          c.post("/api/rules", json={"title": "Eksik", "scope": "camera", "camera_id": dead_cam_id, "zones": [incomplete]}).status_code == 422)
    c.delete(f"/api/rules/{rule3['id']}")

    listing = c.get("/api/rules").json()
    blob = json.dumps(listing)
    check("rule list is slim (no compile logs / raw LLM output)", "compile_logs" not in blob and "raw_llm_response" not in blob)
    r = c.put(f"/api/rules/{rid}", json={"enabled": False})
    check("rule can be disabled", r.status_code == 200 and r.json()["rule"]["enabled"] is False)
    r = c.put(f"/api/rules/{rid}", json={"scope": "system"})
    check("rule scope can be changed to system-wide", r.json()["rule"]["scope"] == "system" and r.json()["rule"]["camera_id"] is None)
    r = c.put(f"/api/rules/{rid}", json={"scope": "camera", "camera_id": "cam_does_not_exist"})
    check("moving a rule to a missing camera is rejected (422)", r.status_code == 422, str(r.status_code))
    check("updating an unknown rule is 404", c.put("/api/rules/rule_nope", json={"enabled": True}).status_code == 404)
    check("plan endpoint of unknown rule is 404", c.get("/api/rules/rule_nope/plan").status_code == 404)
    check("rule delete works and is idempotent-safe",
          c.delete(f"/api/rules/{rid}").status_code == 200 and c.delete(f"/api/rules/{rid}").status_code == 404)
    return rule2["id"]


def test_journal(c, srv, dead_cam_id):
    print("\n[6] Journal, labels, snapshots, storage")
    check("simulating on an unknown camera is 404",
          c.post("/api/anomaly/simulate", json={"camera_id": "nope", "score": 50}).status_code == 404)
    check("out-of-range score is rejected (422)",
          c.post("/api/anomaly/simulate", json={"camera_id": dead_cam_id, "score": 500}).status_code == 422)
    r = c.post("/api/anomaly/simulate", json={"camera_id": dead_cam_id, "score": 77.7})
    entry = r.json()["entry"]
    check("journal entry is created", r.status_code == 200 and entry["tier"] == "critical")
    check("entry of a camera without video has no fake snapshot", entry["snapshot_url"] is None, str(entry["snapshot_url"]))
    eid = entry["id"]
    check("invalid operator label is rejected (422), not silently stored as 'correct'",
          c.post(f"/api/anomaly/{eid}/label", json={"label": "banana"}).status_code == 422)
    check("label on unknown entry is 404", c.post("/api/anomaly/nope/label", json={"label": "correct"}).status_code == 404)
    r = c.post(f"/api/anomaly/{eid}/label", json={"label": "false_positive", "notes": "test"})
    check("operator label is stored", r.status_code == 200 and r.json()["entry"]["operator_label"] == "false_positive")
    j = c.get("/api/anomaly/journal", params={"operator_label": "false_positive"}).json()
    check("journal filter by operator label works", j["count"] == 1 and j["journal"][0]["id"] == eid)
    check("journal limit is honoured", c.get("/api/anomaly/journal", params={"limit": 1}).json()["count"] == 1)
    check("path traversal on clips is blocked", c.get("/api/anomaly/clips/..%2F..%2Fsettings.json").status_code == 404)
    check("path traversal on snapshots is blocked", c.get("/api/anomaly/snapshots/..%2Fanomaly_journal.json").status_code == 404)
    st = c.get("/api/anomaly/storage").json()
    check("storage statistics are reported",
          st["journal_entries"] >= 1 and "orphan_clip_count" in st and "orphan_snapshot_count" in st, json.dumps(st))
    report = c.get("/api/reports/summary", params={"days": 1}).json()["report"]
    check("the report counts real events by hour, camera and decision and leaves out demonstration events",
          len(report["buckets"]) == 24 and report["totals"]["events"] == 0 and report["by_camera"] == []
          and report["totals"]["false_alarm_pct"] is None, json.dumps(report["totals"]))
    check("a report period outside 1-90 days is rejected (422)",
          c.get("/api/reports/summary", params={"days": 0}).status_code == 422
          and c.get("/api/reports/summary", params={"days": 91}).status_code == 422)
    with open(os.path.join(srv.data_dir, "anomaly_journal.json"), encoding="utf-8") as f:
        on_disk = json.load(f)
    check("journal is persisted to the isolated data directory", any(e["id"] == eid for e in on_disk))
    return eid


async def test_sse(base, dead_cam_id):
    print("\n[7] Real-time event stream (SSE)")
    got = {}

    async def listen():
        async with httpx.AsyncClient(timeout=None) as ac:
            async with ac.stream("GET", base + "/api/anomaly/events-stream") as resp:
                got["ctype"] = resp.headers.get("content-type", "")
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        ev = json.loads(line[5:])
                        if ev.get("type") == "connected":
                            got["connected"] = time.perf_counter()
                        if ev.get("type") == "new_anomaly":
                            got["event"] = ev
                            got["t_recv"] = time.perf_counter()
                            return

    task = asyncio.create_task(listen())
    for _ in range(50):
        await asyncio.sleep(0.1)
        if "connected" in got:
            break
    async with httpx.AsyncClient() as ac:
        t_send = time.perf_counter()
        r = await ac.post(base + "/api/anomaly/simulate", json={"camera_id": dead_cam_id, "score": 33})
        sent_id = r.json()["entry"]["id"]
    try:
        await asyncio.wait_for(task, timeout=5)
    except asyncio.TimeoutError:
        task.cancel()
    check("SSE stream connects", "connected" in got, got.get("ctype", ""))
    ok = "event" in got and got["event"]["entry"]["id"] == sent_id
    lat = (got["t_recv"] - t_send) * 1000 if ok else None
    check("a new incident is pushed to clients immediately (< 1 s)", ok and lat < 1000, f"{lat:.0f} ms" if lat else "not received")


async def test_live_video(base, c, sim_ip):
    print("\n[8] Live video (camera simulator)")
    if not port_open(sim_ip, 8891) or not port_open(sim_ip, 8554):
        for n in ("ONVIF registration", "stream goes live", "snapshot", "WebSocket stream", "MJPEG stream",
                  "anomaly scoring", "change detection", "signal-loss handling"):
            skip(n, f"camera simulator not reachable at {sim_ip}")
        return None

    r = c.post("/api/cameras/add", json={"ip": sim_ip, "port": 8892, "username": "admin", "password": "wrong-password",
                                         "rtsp_port": 8554}, timeout=40)
    bad = r.json()["camera"]
    check("wrong ONVIF password is reported (not shown as a healthy camera)", bad["status"] in ("auth_error", "offline"),
          f"{bad['status']}: {bad['status_message']}")
    c.delete(f"/api/cameras/{bad['id']}")

    r = c.post("/api/cameras/add", json={"ip": sim_ip, "port": 8894, "username": "admin", "password": "admin123",
                                         "name": "Sim Kamera", "rtsp_port": 8554}, timeout=40)
    cam = r.json()["camera"]
    cid = cam["id"]
    check("ONVIF registration succeeds", cam["status"] == "online" and cam["stream_uri"].startswith("rtsp://"), cam["status_message"])

    def live():
        for x in c.get("/api/cameras").json()["cameras"]:
            if x["id"] == cid and x["stream_live"]:
                return x
    info = wait_until(live, timeout=30)
    check("stream goes live", bool(info), f"{info['stream_fps']} FPS measured" if info else "never became live")
    if not info:
        return cid

    snap = c.get(f"/api/cameras/{cid}/snapshot")
    check("snapshot is a real JPEG frame", snap.content[:2] == b"\xff\xd8" and len(snap.content) > 4000, f"{len(snap.content)} bytes")
    head = c.head(f"/api/cameras/{cid}/snapshot")
    check("snapshot supports HEAD", head.status_code == 200)

    if websockets is None:
        skip("WebSocket stream", "python 'websockets' package not installed")
    else:
        stamps, frames = [], []
        async with websockets.connect(base.replace("http", "ws") + f"/api/cameras/{cid}/ws", max_size=None) as ws:
            t_end = time.time() + 4.0
            while time.time() < t_end:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.5)
                except asyncio.TimeoutError:
                    continue
                stamps.append(time.perf_counter())
                frames.append(msg)
        fps = (len(stamps) - 1) / (stamps[-1] - stamps[0]) if len(stamps) > 2 else 0
        gaps = sorted(b - a for a, b in zip(stamps, stamps[1:]))
        p95 = gaps[int(len(gaps) * 0.95)] * 1000 if gaps else 0
        check("WebSocket delivers the camera's full frame rate", fps >= 20, f"{fps:.1f} FPS, p95 gap {p95:.0f} ms")
        check("every WebSocket message is a distinct JPEG frame",
              all(f[:2] == b"\xff\xd8" for f in frames) and len(set(frames)) == len(frames), f"{len(frames)} frames")

        capped = []
        async with websockets.connect(base.replace("http", "ws") + f"/api/cameras/{cid}/ws?fps=5", max_size=None) as ws:
            t_end = time.time() + 3.0
            while time.time() < t_end:
                try:
                    capped.append(await asyncio.wait_for(ws.recv(), timeout=1.5))
                except asyncio.TimeoutError:
                    continue
        check("?fps= caps the delivery rate (eco mode)", 8 <= len(capped) <= 22, f"{len(capped)} frames in 3 s at fps=5")

        try:
            async with websockets.connect(base.replace("http", "ws") + "/api/cameras/nope/ws") as ws:
                await asyncio.wait_for(ws.recv(), timeout=2)
            check("WebSocket for unknown camera is closed", False)
        except Exception:
            check("WebSocket for unknown camera is closed", True)

    got = 0
    async with httpx.AsyncClient(timeout=10) as ac:
        async with ac.stream("GET", base + f"/api/cameras/{cid}/stream") as resp:
            ctype = resp.headers.get("content-type", "")
            async for chunk in resp.aiter_bytes():
                got += chunk.count(b"--frame")
                if got >= 10:
                    break
    check("MJPEG stream delivers frames", "multipart/x-mixed-replace" in ctype and got >= 10, f"{got} parts")

    def scored():
        for x in c.get("/api/anomaly/status").json()["cameras"]:
            if x["camera_id"] == cid and x.get("analyzed"):
                return x
    fleet = c.get("/api/anomaly/status").json()
    if not fleet.get("triton_model_ready") and not wait_until(lambda: c.get("/api/anomaly/status").json().get("triton_model_ready"), 8):
        skip("anomaly scoring", "AI server (Triton) not reachable")
    else:
        s = wait_until(scored, timeout=15)
        check("anomaly engine scores the live camera", bool(s), f"score {s['score']} tier {s['tier']}" if s else "no score")
        st = c.get("/api/system/stats").json()["triton"]
        check("telemetry shows the measured anomaly latency", isinstance(st["anomaly_detection_latency_ms"], (int, float)),
              f"{st['anomaly_detection_latency_ms']} ms/stream")

    # -- change detection on live video
    zone = {"id": "zone_cd", "name": "Koridor", "description": "", "zone_type": "change_detection",
            "points": [{"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2}, {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}]}
    rule = c.post("/api/rules", json={"title": "Koridor Engel", "scope": "camera", "camera_id": cid, "zones": [zone]}).json()["rule"]
    r = c.post(f"/api/change-detection/{cid}/zone_cd/capture-reference")
    check("reference frame can be captured from live video", r.status_code == 200 and r.json()["success"], r.text[:120])
    check("capture for an unknown zone is 404", c.post(f"/api/change-detection/{cid}/zone_nope/capture-reference").status_code == 404)

    def cd_running():
        # The zone is evaluated as soon as the rule exists; wait for a result made after the capture
        d = c.get(f"/api/cameras/{cid}/live-detections").json()["data"]
        results = d.get("change_results") or []
        return d if results and results[0]["has_reference"] else None
    d = wait_until(cd_running, timeout=10)
    check("change detection is evaluated on live frames", bool(d) and d["change_results"][0]["has_reference"],
          f"ssim={d['change_results'][0]['ssim']}" if d else "no result")

    # -- a rule that stays violated is one running event, closed when the violation ends.
    # "No airplane in the picture" is a violation that is certain to last.
    plan = {"source_prompt": "test", "selected_model": "coco_detector", "triton_model_name": "coco_detector",
            "detection_targets": [{"class_name": "airplane", "role": "subject"}], "model_classes": ["airplane"],
            "conditions": [{"type": "zone_absence", "targets": ["airplane"], "subject": "airplane",
                            "duration_sec": 0.0, "min_confidence": 0.25}]}
    lasting = c.post("/api/rules", json={"title": "Süren İhlal", "scope": "camera", "camera_id": cid, "zones": [
        {"id": "zone_last", "name": "Alan", "description": "test", "zone_type": "detection", "detection_plan": plan,
         "points": [{"x": 0.05, "y": 0.05}, {"x": 0.95, "y": 0.05}, {"x": 0.95, "y": 0.95}, {"x": 0.05, "y": 0.95}]}]}).json()["rule"]

    def rule_events():
        return [e for e in c.get("/api/anomaly/journal").json()["journal"] if e.get("rule_title") == "Süren İhlal"]
    if not wait_until(lambda: c.get("/api/live/state").json()["detector_ready"], timeout=8):
        skip("lasting rule violation", "AI server (Triton) not reachable")
    else:
        opened = wait_until(rule_events, timeout=10)
        check("a violated rule opens an event that is marked as running",
              bool(opened) and opened[0]["is_ongoing"] and opened[0]["end_time_str"] == "", str(opened)[:160])
        time.sleep(4.0)
        check("while the violation lasts it stays a single event", len(rule_events()) == 1, f"{len(rule_events())} events")
        c.put(f"/api/rules/{lasting['id']}", json={"enabled": False})
        closed = wait_until(lambda: [e for e in rule_events() if not e["is_ongoing"]], timeout=16)
        check("the event is closed with its real duration once the violation ends",
              bool(closed) and len(rule_events()) == 1 and closed[0].get("incident_sec", 0) >= 4.0 and closed[0]["end_time_str"],
              str({k: closed[0].get(k) for k in ("incident_sec", "end_time_str", "duration_sec")}) if closed else "still running")

    snap_entry = c.post("/api/anomaly/simulate", json={"camera_id": cid, "score": 55}).json()["entry"]
    img = c.get(snap_entry["snapshot_url"]) if snap_entry["snapshot_url"] else None
    check("incident snapshot is a stored frame of the incident (not a live URL)",
          bool(img) and img.status_code == 200 and img.content[:2] == b"\xff\xd8"
          and snap_entry["snapshot_url"].startswith("/api/anomaly/snapshots/"), str(snap_entry["snapshot_url"]))

    # -- deleting the camera must release everything that belongs to it
    r = c.delete(f"/api/cameras/{cid}")
    check("deleting a camera removes its rules", r.json().get("removed_rules", 0) >= 1 and
          not any(x["id"] == rule["id"] for x in c.get("/api/rules").json()["rules"]))
    check("deleted camera disappears from live state",
          bool(wait_until(lambda: cid not in c.get("/api/live/state").json()["detections"], timeout=5)))
    check("change-detection reference of the deleted camera is removed",
          c.get(f"/api/change-detection/{cid}/zone_cd").status_code == 404)
    return cid


def test_load(c, srv):
    print("\n[9] Responsiveness under polling load")
    paths = ["/api/live/state", "/api/anomaly/status", "/api/cameras", "/api/rules", "/api/anomaly/stats", "/api/system/stats"]

    async def run():
        lat = []
        errors = 0
        async with httpx.AsyncClient(base_url=srv.base, timeout=10) as ac:
            async def one(p):
                nonlocal errors
                t0 = time.perf_counter()
                try:
                    r = await ac.get(p)
                    if r.status_code != 200:
                        errors += 1
                except Exception:
                    errors += 1
                lat.append((time.perf_counter() - t0) * 1000)
            for _ in range(10):
                await asyncio.gather(*[one(p) for p in paths for _ in range(5)])
        return lat, errors

    lat, errors = asyncio.run(run())
    lat.sort()
    p95 = lat[int(len(lat) * 0.95)]
    check("300 concurrent API calls: no errors", errors == 0, f"{errors} errors")
    check("p95 response time under burst < 250 ms", p95 < 250, f"p50 {statistics.median(lat):.0f} ms, p95 {p95:.0f} ms")


def test_persistence_and_cleanup(c, srv, eid):
    print("\n[10] Persistence across restart, journal clear")
    before_rules = len(c.get("/api/rules").json()["rules"])
    before_cams = len(c.get("/api/cameras").json()["cameras"])
    c.post("/api/settings", json={"anomaly": {"threshold_normal": 31, "threshold_warning": 62}})
    srv.stop()
    for name in ("cameras_db.json", "rules_db.json", "settings.json", "anomaly_journal.json"):
        path = os.path.join(srv.data_dir, name)
        try:
            with open(path, encoding="utf-8") as f:
                json.load(f)
            ok = True
        except Exception as e:  # noqa
            ok = False
        check(f"{name} is valid JSON after shutdown", ok)
    leftovers = [f for f in os.listdir(srv.data_dir) if f.endswith(".tmp")]
    check("no temporary files are left behind by atomic writes", not leftovers, ", ".join(leftovers))
    srv.start()
    check("cameras survive a restart", len(c.get("/api/cameras").json()["cameras"]) == before_cams)
    check("rules survive a restart", len(c.get("/api/rules").json()["rules"]) == before_rules)
    a = c.get("/api/settings").json()["settings"]["anomaly"]
    check("settings survive a restart", (a["threshold_normal"], a["threshold_warning"]) == (31, 62))
    j = c.get("/api/anomaly/journal").json()["journal"]
    check("journal survives a restart", any(e["id"] == eid for e in j))
    check("no journal entry is stuck as 'ongoing' after a restart", not any(e.get("is_ongoing") for e in j))

    snaps_dir = os.path.join(srv.data_dir, "recordings", "snapshots")
    r = c.post("/api/anomaly/clear")
    after = c.get("/api/anomaly/storage").json()
    check("clearing the journal also removes its evidence files",
          r.status_code == 200 and after["journal_entries"] == 0 and after["snapshot_count"] == 0 and after["clip_count"] == 0,
          json.dumps(after))
    check("snapshot directory is empty on disk", not os.listdir(snaps_dir) if os.path.isdir(snaps_dir) else True)


def test_shutdown_and_single_instance(srv):
    print("\n[11] Shutdown with open streams, single-instance guard")

    # -- a second backend on the same data directory must refuse to start
    env = dict(os.environ)
    env.update({"AEGIS_DATA_DIR": srv.data_dir, "EVREN_API_KEY": "", "AEGIS_LOCK_WAIT_SEC": "1.5",
                "PYTHONPATH": PROJECT_ROOT + os.pathsep + env.get("PYTHONPATH", "")})
    second_port = free_port()
    second = subprocess.run(
        [sys.executable, "-m", "uvicorn", "WebInterface.backend.server:app", "--host", "127.0.0.1",
         "--port", str(second_port), "--log-level", "warning"],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    check("a second server on the same data directory refuses to start",
          second.returncode != 0 and "başka bir AegisVision sunucusu" in (second.stderr + second.stdout),
          f"exit code {second.returncode}")
    check("the running server is unaffected by the rejected second instance",
          httpx.get(srv.base + "/api/health", timeout=3).status_code == 200)

    # -- browsers keep event streams / video sockets open forever: shutdown must not wait for them
    async def hold_connections_and_stop():
        async with httpx.AsyncClient(timeout=None) as ac:
            async with ac.stream("GET", srv.base + "/api/anomaly/events-stream") as resp:
                first = await resp.aiter_lines().__anext__()
                ws = None
                if websockets is not None:
                    cams = (await ac.get(srv.base + "/api/cameras")).json()["cameras"]
                    if cams:
                        ws = await websockets.connect(srv.base.replace("http", "ws") + f"/api/cameras/{cams[0]['id']}/ws", max_size=None)
                t0 = time.time()
                srv.proc.send_signal(signal.SIGTERM)
                while srv.proc.poll() is None and time.time() - t0 < 20:
                    await asyncio.sleep(0.1)
                took = time.time() - t0
                if ws is not None:
                    try:
                        await ws.close()
                    except Exception:
                        pass
                return first.startswith("data:"), took

    connected, took = asyncio.run(hold_connections_and_stop())
    check("server exits promptly on SIGTERM although an event stream and a video socket are open",
          connected and srv.proc.poll() is not None and took < 8.0, f"{took:.1f}s")

    # -- an immediate restart takes over the data directory cleanly
    startup = srv.start()
    check("immediate restart acquires the data directory and serves again", startup < 30, f"{startup:.1f}s to ready")


def test_summary_shaping():
    print("\n[12] Incident summary shaping (no model needed)")
    sys.path.insert(0, PROJECT_ROOT)
    from Rule_Generator_LLM.vlm_summarizer import compact_summary

    answer = ("**Değerlendirme:** BELİRSİZ\n**Özet Başlık:** Bir kişi koridorda yere düştü. Sonra kalktı.\n"
              "- Kişi koridorda yere düştü.\n- Yanında başka kimse yok. Kapı açık.\n- Üçüncü madde.\n- Dördüncü madde.\n"
              "**Öneri:** Kişinin durumunu kontrol edin.")
    headline, note, verdict = compact_summary(answer)
    check("summary keeps one headline sentence", headline == "Bir kişi koridorda yere düştü.", headline)
    check("summary drops the detail that repeats the headline and keeps at most two",
          note.count("\n- ") == 2 and "Kişi koridorda" not in note.split("\n", 1)[1], note)
    check("verdict is read (also with a dotted capital I) and kept out of the note",
          verdict == "unclear" and "Değerlendirme" not in note, f"{verdict} / {note}")
    verdicts = [compact_summary(f"**Değerlendirme:** {word}\n**Özet Başlık:** Koridor boş.")[2]
                for word in ("GERÇEK", "Olağan.", "bilmiyorum")]
    check("verdict words map to confirmed / normal, an unknown word to none",
          verdicts == ["confirmed", "normal", None], str(verdicts))
    check("an answer without a headline is rejected", compact_summary("**Değerlendirme:** OLAĞAN\n") is None)


def test_tracking_and_rule_logic():
    print("\n[13] Tracking, rule logic, schedules, reports and compiler answers (no model needed)")
    sys.path.insert(0, PROJECT_ROOT)
    from Rule_Generator_LLM.compiler import RuleCompiler, UnsupportedRule
    from Rule_Generator_LLM.evaluator import ConditionEvaluator, DetectionBox
    from Rule_Generator_LLM.schema import DetectionPlan
    from Rule_Generator_LLM.tracker import COAST_SEC, FORGET_SEC, ObjectTracker

    person = lambda x: DetectionBox(xyxy=[x, 100, x + 40, 200], conf=0.8, cls_name="Person")  # noqa: E731
    tracker = ObjectTracker()
    first = tracker.update([person(100)], now=0.0)
    second = tracker.update([person(104)], now=0.1)
    check("an object is confirmed on its second frame and keeps its identity",
          not first[0].confirmed and second[0].confirmed and first[0].track_id == second[0].track_id)
    missed = tracker.update([], now=0.2)
    check("a confirmed object missed for one frame is still reported (coasting)",
          len(missed) == 1 and missed[0].coasting and missed[0].track_id == first[0].track_id)
    check("it is no longer reported after the coasting time", tracker.update([], now=0.2 + COAST_SEC + 0.1) == [])
    back = tracker.update([person(110)], now=1.5)
    check("an object that comes back soon keeps its identity", back[0].track_id == first[0].track_id)
    tracker.update([], now=1.5 + FORGET_SEC + 0.5)
    check("an object that comes back late is a new object",
          tracker.update([person(110)], now=5.0)[0].track_id != first[0].track_id)

    def first_alarm(scene, condition, seconds=12):
        plan = DetectionPlan(source_prompt="t", detection_targets=[{"class_name": "Person", "role": "subject"}],
                             conditions=[dict(condition, targets=["Person"], min_confidence=0.25)])
        evaluator, tracker = ConditionEvaluator(), ObjectTracker()
        for step in range(seconds * 10):
            now = step * 0.1
            boxes = [box for box in tracker.update(scene(now), now) if box.confirmed]
            if evaluator.evaluate(plan, boxes, zone_id="zone", now=now).alarm:
                return round(now, 1)
        return None

    waiting = {"type": "loitering", "subject": "Person", "duration_sec": 5.0}
    alone = first_alarm(lambda now: [person(100)], waiting)
    relay = first_alarm(lambda now: [person(100)] if now < 4.0 else [person(400)], waiting)
    gap = first_alarm(lambda now: [] if 2.0 <= now < 2.5 else [person(100)], waiting)
    check("waiting time is measured per object: a second person does not inherit the first one's clock",
          alone is not None and alone < 5.5 and relay is not None and relay > 8.5, f"alone {alone}s, relay {relay}s")
    check("a short detection gap does not restart the waiting clock", gap is not None and gap < 5.5, f"{gap}s")
    presence = {"type": "zone_presence"}
    check("a detection that appears on a single frame raises no alarm",
          first_alarm(lambda now: [person(100)] if abs(now - 3.0) < 0.05 else [], presence) is None)
    real = first_alarm(lambda now: [person(100)] if now >= 3.0 else [], presence)
    check("a real object raises the alarm on its second frame", real is not None and real <= 3.2, f"{real}s")

    from datetime import datetime
    from Rule_Generator_LLM import schedule as rule_schedule
    from Rule_Generator_LLM.manual import build_plan, describe_plan
    night = rule_schedule.normalize({"start": "22:00", "end": "6.00", "days": [4, 9]}, source="text")  # Friday night
    at = lambda text: datetime.strptime(text, "%Y-%m-%d %H:%M")  # noqa: E731  (2026-10-09 is a Friday)
    check("a schedule is cleaned up (time format, impossible day)",
          night == {"source": "text", "start": "22:00", "end": "06:00", "days": [4]}, str(night))
    check("a window past midnight belongs to the day it starts on",
          [rule_schedule.is_active(night, at(moment)) for moment in
           ("2026-10-09 21:59", "2026-10-09 22:00", "2026-10-10 05:59", "2026-10-10 06:00", "2026-10-10 23:00")]
          == [False, True, True, False, False])
    check("no schedule, or one without hours, means always",
          rule_schedule.is_active(None) and rule_schedule.is_active({"source": "user"})
          and rule_schedule.normalize({"start": "25:00", "end": "x"}) is None)
    check("the whole day written as 00:00-23:59 is understood",
          rule_schedule.describe(rule_schedule.normalize({"start": "00:00", "end": "23:59", "days": [5, 6]})) == "Tüm gün · Hafta sonu")
    sentences = [build_plan({"subject": subject, "condition": condition, "value": value}).source_prompt
                 for subject, condition, value in (("person", "more_than", 3), ("vehicle", "presence", None),
                                                   ("person", "absence", 120), ("forklift", "waiting", 40))]
    check("list choices become a plan and a sentence that says what it does",
          sentences == ["Bölgede 3'ten fazla kişi olunca", "Araç bölgede görülünce",
                        "Bölgede 2 dakika boyunca hiç kişi yokken", "Forklift bölgede 40 saniyeden uzun kalınca"], str(sentences))
    check("an equipment plan is described as what is missing on the person",
          describe_plan({"conditions": [{"type": "zone_absence", "subject": "Person", "required": ["Hardhat"]}]})
          == "Bölgedeki kişi üzerinde baret yoksa")

    from WebInterface.backend.reports import build_report
    day = 86400.0
    now = at("2026-10-09 12:00").timestamp()
    journal = [
        {"id": "rule_a", "timestamp": now - 3600, "camera_name": "Depo", "rule_title": "Baret", "incident_sec": 600,
         "operator_label": "correct", "ai_verdict": "confirmed"},
        {"id": "rule_b", "timestamp": now - 2 * day, "camera_name": "Depo", "rule_title": "Baret", "incident_sec": 60,
         "operator_label": "false_positive", "ai_verdict": "confirmed"},
        {"id": "anom_c", "timestamp": now - 2 * day, "camera_name": "Ofis", "operator_label": "false_positive", "ai_verdict": "normal"},
        {"id": "anom_d", "timestamp": now - 20 * day, "camera_name": "Ofis"},
        {"id": "sim_e", "timestamp": now - 60, "camera_name": "Ofis"},
    ]
    week = build_report(journal, 7, now=now)
    check("the weekly report has one bar per day and counts each event once",
          len(week["buckets"]) == 7 and week["buckets"][-1] == {"label": "09.10", "rule": 1, "movement": 0}
          and week["buckets"][-3] == {"label": "07.10", "rule": 1, "movement": 1} and week["totals"]["events"] == 3,
          json.dumps(week["buckets"]))
    check("it reports the false alarm rate of the reviewed events and how long each rule was violated",
          week["totals"]["false_alarm_pct"] == 66.7 and week["by_rule"][0]["name"] == "Baret" and week["by_rule"][0]["total_sec"] == 660.0,
          f"{week['totals']} / {week['by_rule']}")
    check("it says how often the summary's verdict matched the operator",
          week["summary_verdict"] == {"compared": 3, "agreed": 2}, str(week["summary_verdict"]))
    check("a full journal whose oldest event is inside the period is reported as incomplete",
          build_report(journal[:3], 7, now=now, capacity=3)["incomplete"] and not week["incomplete"])

    compiler = RuleCompiler.__new__(RuleCompiler)  # parsing needs no connection to the language model
    answer = {"selected_model": "coco_detector", "detection_targets": [{"class_name": "person", "role": "forbidden"}],
              "conditions": [{"type": "zone_presence", "targets": ["person"]}]}
    partial = compiler._parse_and_validate(json.dumps(dict(answer, feasibility="partial", user_note="Kişileri ayırt edemem.")), "t")
    full = compiler._parse_and_validate(json.dumps(dict(answer, feasibility="full", user_note="gereksiz not")), "t")
    check("a partial rule carries the compiler's note, a full one never does",
          partial.feasibility == "partial" and partial.user_note == "Kişileri ayırt edemem." and full.user_note is None)
    try:
        compiler._parse_and_validate(json.dumps({"feasibility": "none", "user_note": "Ses alamam.",
                                                 "detection_targets": [], "conditions": []}), "t")
        refused = ""
    except UnsupportedRule as exc:
        refused = str(exc)
    check("a request the system cannot serve is refused with the explanation", refused == "Ses alamam.", refused)


def test_translations():
    print("\n[14] Interface translations (no server needed)")
    import glob
    import re
    from html.parser import HTMLParser

    frontend = os.path.join(PROJECT_ROOT, "WebInterface", "frontend")
    with open(os.path.join(frontend, "js", "i18n-en.js"), encoding="utf-8") as f:
        source = f.read()
    body = source.split("// catalogue:begin", 1)[1].split("// catalogue:end", 1)[0]
    catalogue = json.loads(body.strip().removeprefix("export default").strip().rstrip(";"))
    check("the English catalogue is valid JSON between its markers", isinstance(catalogue, dict) and len(catalogue) > 100,
          f"{len(catalogue)} entries")

    wanted = set()
    for path in glob.glob(os.path.join(frontend, "js", "*.js")):
        if path.endswith(("i18n.js", "i18n-en.js")):
            continue
        with open(path, encoding="utf-8") as f:
            code = f.read()
        wanted.update(m.group(1) for m in re.finditer(r'\bt\(\s*"((?:[^"\\]|\\.)*)"', code))
        for m in re.finditer(r'\bt\([^()"]*\?\s*"((?:[^"\\]|\\.)*)"\s*:\s*"((?:[^"\\]|\\.)*)"', code):
            wanted.update(m.groups())
    missing = sorted(text for text in wanted if text not in catalogue)
    check("every text passed to t() has an English entry", not missing, "; ".join(missing[:5]))

    class Page(HTMLParser):
        texts, skip = set(), 0
        def handle_starttag(self, tag, attrs):
            self.skip += tag in ("script", "style", "svg")
            self.texts.update(v.strip() for k, v in attrs if k in ("placeholder", "title", "aria-label", "alt") and v)
        def handle_endtag(self, tag):
            self.skip -= tag in ("script", "style", "svg")
        def handle_data(self, data):
            if not self.skip and data.strip():
                self.texts.add(data.strip())
    page = Page()
    with open(os.path.join(frontend, "index.html"), encoding="utf-8") as f:
        page.feed(f.read())
    words = re.compile(r"[a-zçğıöşü]{2,}", re.IGNORECASE)
    untranslated = sorted(text for text in page.texts if words.search(text) and text not in catalogue)
    check("every text of index.html has an English entry", not untranslated, "; ".join(untranslated[:5]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sim-ip", default=os.environ.get("SIM_IP", ""), help="IP the camera simulator advertises (default: auto-detect)")
    ap.add_argument("--keep", action="store_true", help="keep the temporary data directory")
    args = ap.parse_args()

    sim_ip = args.sim_ip
    if not sim_ip:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            sim_ip = s.getsockname()[0]
            s.close()
        except OSError:
            sim_ip = "127.0.0.1"

    data_dir = tempfile.mkdtemp(prefix="aegis_syscheck_")
    srv = Server(data_dir)
    print(f"AegisVision system check — data dir {data_dir}")
    try:
        startup = srv.start()
        print(f"backend ready on {srv.base}")
        with httpx.Client(base_url=srv.base, timeout=20) as c:
            test_static_and_health(c, srv, startup)
            test_idle_cpu(srv)
            test_settings(c)
            dead_cam = test_camera_validation(c)
            test_rules(c, dead_cam)
            eid = test_journal(c, srv, dead_cam)
            asyncio.run(test_sse(srv.base, dead_cam))
            asyncio.run(test_live_video(srv.base, c, sim_ip))
            test_load(c, srv)
            test_persistence_and_cleanup(c, srv, eid)
            test_shutdown_and_single_instance(srv)
            test_summary_shaping()
            test_tracking_and_rule_logic()
            test_translations()
    except Exception as e:  # a crash of the harness is a failure, never a silent pass
        import traceback
        traceback.print_exc()
        record("FAIL", "test harness completed", repr(e))
    finally:
        srv.stop()
        errors = ""
        try:
            with open(srv.log_path, encoding="utf-8", errors="replace") as f:
                log = f.read()
            errors = "\n".join(l for l in log.splitlines() if "Traceback" in l or "ERROR" in l)
        except OSError:
            log = ""
        check("server log contains no tracebacks / errors", not errors, errors[:300])
        if not args.keep:
            shutil.rmtree(data_dir, ignore_errors=True)

    passed = sum(1 for s, _, _ in RESULTS if s == "PASS")
    failed = [r for r in RESULTS if r[0] == "FAIL"]
    skipped = sum(1 for s, _, _ in RESULTS if s == "SKIP")
    print(f"\n{'=' * 64}\n {passed} passed, {len(failed)} failed, {skipped} skipped\n{'=' * 64}")
    for _, name, detail in failed:
        print(f"  FAILED: {name}  [{detail}]")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
