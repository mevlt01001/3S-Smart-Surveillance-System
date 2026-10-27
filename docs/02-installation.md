# 02 — Installation and start-up

## Requirements

| Requirement | Note |
| :--- | :--- |
| Linux | Tested on Ubuntu 22.04. |
| NVIDIA graphics card + driver | The models run with TensorRT. Development machine: GTX 1650 Ti (4 GB). |
| Docker + NVIDIA Container Toolkit | The analysis server (Triton) runs in a container. Install script: `sudo bash Object_Detection/install_docker_prerequisites.sh` |
| Python 3.10 | The `.conda/` environment at the repository root is used. |
| ffmpeg | Encodes event videos and reads frames from videos. `sudo apt install ffmpeg` |
| Browser | Current Chrome / Edge. Not tested in Firefox. |

To see the state of the environment in one report: `python Object_Detection/check_environment.py`

## First installation

### 1. Python environment

```bash
conda create -p ./.conda python=3.10 -y
```
```bash
./.conda/bin/pip install -r requirements.txt
```

### 2. Model files

Model weights are **not** kept in the repository (`.gitignore`). Each model goes into its own directory of
the Triton model repository:

```
Object_Detection/model_repository/
├── anomaly_detector/   config.pbtxt   1/model.plan      input: video_segment [3,16,224,224]  → logits [1]
├── safety_detector/    config.pbtxt   1/model.plan      input: images [3,640,640]            → output0 [14,N]
├── coco_detector/      config.pbtxt   1/model.plan      input: images [3,640,640]            → output0 [84,N]
└── yoloe_detector/     config.pbtxt   1/model.plan      input: images + text_feats [K,512]   → outputs [K+4,8400]
```

`model.plan` is a TensorRT engine and is **specific to the graphics card it was built on**; it cannot be
copied to another machine. If you have the ONNX files (`1/model.onnx`), build the engines on that machine:

```bash
./Object_Detection/convert_to_tensorrt.sh
```
```bash
./Object_Detection/apply_tensorrt_configs.sh
```

The first converts the ONNX files into engines with `trtexec` inside the container (25–45 minutes on a
4 GB card); the second updates the `config.pbtxt` files for TensorRT and restarts Triton.

### 3. Access key

The language model service that interprets rule descriptions and writes incident summaries needs a key.
Copy the template and enter the key:

```bash
cp .env.example .env
```

`.env` is never committed. Without a key the system still runs: rules described in a sentence show
"Could not be prepared" and events are recorded without summaries. Rules defined from lists, obstruction
/ change rules and unusual activity detection do not need this service.

## Start-up

There are three processes. Their order matters: the web server looks for the analysis server when it starts.

### 1. Analysis server

```bash
./Object_Detection/start_triton_docker.sh
```

The container is called `triton_yoloe_server`, its HTTP port is `8000`. To confirm that the models are loaded:

```bash
curl -s localhost:8000/v2/health/ready -o /dev/null -w "%{http_code}\n"
```

### 2. Camera simulator (only without real cameras)

```bash
cd Camera_System_Simulator && ./start.sh --dir ../TestVideoSet
```

Every video in the directory becomes a camera: video at `rtsp://<ip>:8554/<file name>`, the ONVIF service
on one port per camera starting at `8891`. Default account `admin` / `admin123`. The simulator has its own
Python environment (`Camera_System_Simulator/venv`).

### 3. Web server

```bash
./WebInterface/run.sh
```

The interface opens at **http://localhost:8500**. The script starts the server with `--reload`: when a
Python file under `WebInterface/backend` changes, the server restarts itself.

To keep it running after the terminal is closed:

```bash
setsid nohup ./WebInterface/run.sh > aegis.log 2>&1 < /dev/null &
```

## First use

1. On the **Cameras** page press "Find cameras", enter the cameras' user name and password and choose
   "Add all". (For a camera that is not found: "Add manually".)
2. Confirm in **Live view** that pictures arrive.
3. Under **Settings → Detection**, keep "Detect unusual activity" switched on.
4. Optionally define a zone rule under **Rules**.
5. To use the interface in English, choose **Settings → Appearance → English** (per device).

Details: [03 — User guide](03-user-guide.md).

## Stopping

```bash
pkill -f "uvicorn WebInterface.backend.server:app"
```
```bash
cd Camera_System_Simulator && ./stop.sh
```
```bash
docker stop triton_yoloe_server
```

When it shuts down, the web server closes its open video and notification connections itself and exits
in under a second.

## Ports

| Port | Process | Use |
| :--- | :--- | :--- |
| 8500 | Web server | Interface and API |
| 8000 | Triton | HTTP inference (8001 gRPC, 8002 metrics) |
| 8554 | Simulator (mediamtx) | RTSP |
| 8891–… | Simulator | ONVIF, one per camera |
| 3702/udp | — | ONVIF discovery (WS-Discovery multicast) |

## Running a second instance

To experiment without touching the real data, give a separate data directory and port:

```bash
AEGIS_DATA_DIR=/tmp/aegis-test EVREN_API_KEY="" .conda/bin/python -m uvicorn WebInterface.backend.server:app --port 8502
```

`EVREN_API_KEY=""` switches external service calls off. A second server never starts on the same data
directory; it exits with a clear error message (see [04 — Architecture](04-architecture.md), "Single-instance lock").

## Network notes

- The server listens on `0.0.0.0:8500`: anyone on the same network can reach the interface. **There is no
  authentication**; do not expose it beyond the local network.
- Camera discovery runs separately through every active network card of the machine; cameras on a
  different subnet are not found, use "Add manually".
- A camera is stored with the IP address it had when it was added. If its address changes, remove it and
  add it again. (The simulator advertises the address the machine had when the simulator started; restart
  it after the machine's address changes.)
