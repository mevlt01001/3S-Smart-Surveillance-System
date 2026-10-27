# Object Detection

This package gives Smart Surveillance System its eyes for rules. Every rule a user writes — "no one without a hard hat",
"no forklift in this lane", "no bag left here" — is ultimately answered by the detectors served from here.

Its centrepiece is **YOLOE**, an open-vocabulary detector exported in a **decoupled** form that separates
the image backbone from the text embeddings. The practical consequence is what makes plain-language rules
possible:

> **A single TensorRT engine or ONNX model detects whatever class names you give it at run time**
> (`["person", "knife", "backpack", "pallet jack", ...]`) — no retraining, no re-export, no engine rebuild.

---

## Models served to the system

The Triton model repository (`model_repository/`) holds four TensorRT models. The rule compiler picks the
most suitable detector for each rule; the unusual-activity service uses the fourth.

| Triton model | What it detects | Why it is there |
| :--- | :--- | :--- |
| `safety_detector` | Hard hat / no hard hat, safety vest / no vest, mask / no mask, person, safety cone, machinery, vehicle | Personal protective equipment is the most common industrial rule; a dedicated model makes it precise. |
| `coco_detector` | The 80 standard COCO classes (people, vehicles, bags, animals, …) | Fast and reliable for everyday objects. |
| `yoloe_detector` | Any object named in words | Covers everything the other two do not know, so a user is never limited to a fixed list. |
| `anomaly_detector` | Not objects: scores 16-frame video clips for abnormal events | Catches incidents no rule anticipated (trained in `Anomaly_Detection/`). |

All four run on one GPU behind a single Triton server and accept batches, so one card serves the whole
camera fleet.

---

## Using the library

```python
from Object_Detection import YOLODetector

# 1. Create the detector — locally (ONNX / TensorRT) or through a Triton server
detector = YOLODetector(
    model_path="yoloe-26l-seg_decoupled_sim.onnx",   # or "yoloe_decoupled.engine"
    # backend="triton", triton_url="localhost:8000",  # Triton mode, as used by the web system
    classes=["person", "bus", "shoes"],             # initial classes
    conf_thres=0.25,
    iou_thres=0.45,
    device="cuda",
)

# 2. Detect — from a file path, an OpenCV array or a PIL image
results = detector.detect("bus.jpg")

# 3. Read the detections
for box in results.boxes:
    print(f"{box.cls_name} ({box.conf:.2f}) -> {box.xyxy}")

# 4. Draw them and save the picture
results.save("detections.jpg")

# 5. Change the classes at any time — the engine is NOT reloaded
detector.set_classes(["backpack", "sunglasses", "jacket"])
new_results = detector.detect("bus.jpg")
```

---

## Environment check

One report on GPU, CUDA, Docker, the NVIDIA Container Toolkit and the Triton server — the first thing to
run when something does not start:

```bash
python Object_Detection/check_environment.py
```

---

## Running the Triton inference server

The model repository and its `config.pbtxt` files are ready to use.

**Prerequisite** — Docker and the NVIDIA Container Toolkit, installed in one step if missing:

```bash
sudo bash Object_Detection/install_docker_prerequisites.sh
```

**Option 1 — script (recommended):**

```bash
./Object_Detection/start_triton_docker.sh
```

**Option 2 — Docker Compose:**

```bash
docker compose -f Object_Detection/docker-compose.yml up -d
```

**Option 3 — plain `docker run`:**

```bash
docker run --gpus all --rm -it \
    --shm-size=1g --ulimit memlock=-1 --ulimit stack=67108864 \
    -p 8000:8000 -p 8001:8001 -p 8002:8002 \
    -v $(pwd)/Object_Detection/model_repository:/models \
    nvcr.io/nvidia/tritonserver:24.01-py3 \
    tritonserver --model-repository=/models --log-verbose=0
```

**Check that it answers** (`200` means ready):

```bash
curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/v2/health/ready
```

```bash
python Object_Detection/triton_inference_test.py
```

---

## Building a TensorRT engine

TensorRT is what makes real-time detection on many cameras affordable on a single GPU. To turn the ONNX
model into an engine:

```bash
trtexec --onnx=yoloe_decoupled_sim.onnx \
        --saveEngine=yoloe_decoupled.engine \
        --fp16 \
        --minShapes=images:1x3x640x640,text_feats:1x1x512 \
        --optShapes=images:1x3x640x640,text_feats:1x5x512 \
        --maxShapes=images:1x3x640x640,text_feats:1x80x512
```

> The `min` / `opt` / `max` shape profiles let one engine accept anywhere from 1 to 80 classes.

`convert_to_tensorrt.sh` and `apply_tensorrt_configs.sh` automate the conversion for the Triton repository.

---

## Package layout

| File | Role |
| :--- | :--- |
| `detector.py` | The `YOLODetector` API: detection, run-time classes, detection from a compiled rule plan. |
| `triton_backend.py`, `triton_fast_client.py` | Inference through Triton — the path the web system uses — with a zero-copy HTTP client. |
| `onnx_backend.py` | Local inference with ONNX Runtime. |
| `trt_backend.py` | Local inference with TensorRT and a `trtexec` command builder. |
| `text_encoder.py`, `text_feature_cache.py` | MobileCLIP text vectors for class names, cached on disk so repeated rules cost nothing. |
| `decoupled_model.py` | Wrapper that separates YOLOE from its text input, and the ONNX export. |
| `utils.py` | Letterboxing, box scaling, NMS and `DetectionResult`. |
| `tests/` | Unit and end-to-end tests (`python Object_Detection/run_tests.py`). |
| Tools | `check_environment.py`, `benchmark_triton.py`, `triton_inference_test.py`, `triton_multi_model_test.py`, `start_triton_docker.sh`, `install_docker_prerequisites.sh`, `convert_to_tensorrt.sh`, `apply_tensorrt_configs.sh`. |

> **Note:** the tests load models and need several gigabytes of GPU memory. Do not run them while the live
> system is serving cameras.
