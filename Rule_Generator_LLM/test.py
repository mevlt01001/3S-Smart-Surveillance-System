import os
import cv2
import base64
import time
import numpy as np
from typing import Optional, Union, List
from openai import OpenAI

# Görsel ön işleme ve boyutlandırma sabitleri
VLM_MAX_EDGE = 448
VLM_DIMENSION_ALIGNMENT = 32
VLM_TARGET_FRAMES = 8
VLM_FORMAT = "image_url-multi_frames"


class EVREN_MODEL_MANAGER:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
    ):
        self.model_name = model_name or os.getenv("EVREN_VLM_MODEL", "qwen3-vl-30b")
        self.temperature = temperature
        self.system_prompt = system_prompt
        self.base_url = base_url or os.getenv("EVREN_BASE_URL", "https://evren-llmapi.ssyz.org.tr/v1")
        self.api_key = api_key or os.getenv("EVREN_API_KEY", "evren_llm_g4wcNdOYXkr5gy_CVF2iotHvHQmtwy3x3jJcPvLaaO8")

        if not self.base_url or not self.api_key:
            raise RuntimeError("API anahtarı veya Base URL eksik.")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=1800,
        )
        self.history = []
        self.reset_context()

    def reset_context(self):
        """Sohbet geçmişini sıfırlar."""
        self.history = []
        if self.system_prompt:
            self.history.append({"role": "system", "content": self.system_prompt})

    @staticmethod
    def _resize(frame: np.ndarray) -> np.ndarray:
        """Görsel boyutlarını 32'nin katına hizalar ve max edge sınırına çeker."""
        h, w = frame.shape[:2]
        scale = min(1.0, VLM_MAX_EDGE / max(h, w))
        nw = max(VLM_DIMENSION_ALIGNMENT, int(round(w * scale / VLM_DIMENSION_ALIGNMENT) * VLM_DIMENSION_ALIGNMENT))
        nh = max(VLM_DIMENSION_ALIGNMENT, int(round(h * scale / VLM_DIMENSION_ALIGNMENT) * VLM_DIMENSION_ALIGNMENT))
        if nw == w and nh == h:
            return frame
        return cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)

    @classmethod
    def extract_8_frames_from_video(cls, video_path: str) -> List[np.ndarray]:
        """
        Video dosyasından başlangıç ve bitiş framelerini ASLA dahil etmeden,
        aralıktan eşit aralıklı 8 kare çıkarır.
        """
        cap = cv2.VideoCapture(video_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
            raise RuntimeError(f"Video okunamadı veya kare sayısı geçersiz: {video_path}")

        # 10 eşit nokta belirle: [0, p1, p2, p3, p4, p5, p6, p7, p8, N-1]
        # [1:-1] dilimlemesi ile ilk (0) ve son (N-1) kare hariç tam 8 kare elde edilir.
        if total_frames > VLM_TARGET_FRAMES + 2:
            indices = np.linspace(0, total_frames - 1, VLM_TARGET_FRAMES + 2, dtype=int)[1:-1]
        else:
            start_idx = 1 if total_frames > 2 else 0
            end_idx = total_frames - 2 if total_frames > 2 else total_frames - 1
            indices = np.linspace(start_idx, end_idx, VLM_TARGET_FRAMES, dtype=int)

        frames = []
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
            ret, frame = cap.read()
            if ret:
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frames.append(cls._resize(frame_rgb))

        cap.release()

        while len(frames) < VLM_TARGET_FRAMES and len(frames) > 0:
            frames.append(frames[-1])

        return frames[:VLM_TARGET_FRAMES]

    def _prepare_frames(self, frames: Union[np.ndarray, List[np.ndarray]]) -> List[np.ndarray]:
        """NumPy dizisinden başlangıç/bitiş hariç 8 kare seçer."""
        if isinstance(frames, np.ndarray):
            arr = frames
        else:
            arr = np.asarray(frames)

        if arr.ndim == 3:
            arr = arr[None, ...]

        total = arr.shape[0]
        if total > VLM_TARGET_FRAMES + 2:
            idxs = np.linspace(0, total - 1, VLM_TARGET_FRAMES + 2, dtype=int)[1:-1]
            selected = arr[idxs]
        elif total > 2:
            idxs = np.linspace(1, total - 2, VLM_TARGET_FRAMES, dtype=int)
            selected = arr[idxs]
        else:
            selected = arr

        resized = [self._resize(f) for f in selected]
        while len(resized) < VLM_TARGET_FRAMES and len(resized) > 0:
            resized.append(resized[-1])

        return resized[:VLM_TARGET_FRAMES]

    @staticmethod
    def _frame_to_b64(frame_rgb: np.ndarray) -> str:
        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        _, buffer = cv2.imencode(".jpg", frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        return base64.b64encode(buffer).decode("utf-8")

    def run(
        self,
        text: str,
        frames: Optional[Union[np.ndarray, List[np.ndarray]]] = None,
        video_path: Optional[str] = None,
        *,
        raise_on_error: bool = False
    ) -> str:
        content = []
        if text:
            content.append({"type": "text", "text": text})

        selected_frames = []
        if video_path is not None and os.path.exists(video_path):
            selected_frames = self.extract_8_frames_from_video(video_path)
        elif frames is not None:
            selected_frames = self._prepare_frames(frames)

        for frame in selected_frames:
            b64_str = self._frame_to_b64(frame)
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64_str}"}
            })

        self.history.append({"role": "user", "content": content})
        marker = f"[{VLM_FORMAT} frames={len(selected_frames)} model={self.model_name}]"

        try:
            started = time.perf_counter()
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=self.history,
                temperature=self.temperature,
            )
            elapsed = time.perf_counter() - started
            text_out = response.choices[0].message.content or ""
            self.history.append({"role": "assistant", "content": text_out})
            return f"{marker} (time={elapsed:.2f}s)\n{text_out}"
        except Exception as e:
            self.history.pop()
            if raise_on_error:
                raise
            msg = str(e)
            if len(msg) > 400:
                msg = msg[:400] + "…"
            return f"{marker}\n[VLM HATA]: {msg}"


if __name__ == "__main__":
    model = EVREN_MODEL_MANAGER(
        api_key="REMOVED_API_KEY",
        base_url="https://evren-llmapi.ssyz.org.tr/v1",
        model_name="qwen3-vl-30b"
    )
    test_video = "/home/n3uron/workspace/SmartSurveillanceSystem/Anomaly_Detection/Test_Videos/test_video_0.mp4"
    prompt = (
        "Olay akışını ve güvenlik açısından herhangi bir anomali/şüpheli durum olup olmadığını kronolojik olarak açıkla."
    )
    
    print("Video analiz ediliyor (8 kare çıkarılıyor, başlangıç ve bitiş hariç)...")
    result = model.run(text=prompt, video_path=test_video)
    print("\n--- MODEL YANITI ---")
    print(result)
