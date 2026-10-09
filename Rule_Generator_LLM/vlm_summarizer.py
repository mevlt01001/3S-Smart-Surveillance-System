"""
Incident summarizer: looks at a handful of frames of a recorded incident and writes the
short note an operator reads in the event window (one headline, a few details, one advice),
together with its verdict on whether the footage shows anything that needs attention.

The frame sampling helpers at the top are plain image code and need no credentials; the
event API uses them to show the frames of a clip.
"""

import base64
import logging
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from openai import OpenAI

from . import llm_config

logger = logging.getLogger("aegis.summarizer")

# Frames sent to the model: few and small, which keeps a summary around one second
FRAME_COUNT = 8
FRAME_MAX_EDGE = 256
FRAME_ALIGNMENT = 32

# The summary is a note for an operator, not a report
SUMMARY_MAX_WORDS = 60
HEADLINE_MAX_WORDS = 12   # the headline is also the title of the event in lists
SUMMARY_MAX_DETAILS = 2
SUMMARY_MAX_TOKENS = 240

# What the model answers on its "Değerlendirme" line -> verdict stored with the event.
# Matched by the first letters: str.lower() does not turn "İ" into a plain "i".
VERDICTS = {"gerç": "confirmed", "olağ": "normal", "bel": "unclear"}

JpegFrame = Tuple[float, bytes]  # (capture time, JPEG bytes) as kept in the camera ring buffer


# ----------------------------------------------------------------- frame sampling
def _resize(frame: np.ndarray) -> np.ndarray:
    """Shrinks a frame so its longer edge fits FRAME_MAX_EDGE, with both edges aligned as the model expects."""
    height, width = frame.shape[:2]
    scale = min(1.0, FRAME_MAX_EDGE / max(height, width))
    new_width = max(FRAME_ALIGNMENT, int(round(width * scale / FRAME_ALIGNMENT) * FRAME_ALIGNMENT))
    new_height = max(FRAME_ALIGNMENT, int(round(height * scale / FRAME_ALIGNMENT) * FRAME_ALIGNMENT))
    if (new_width, new_height) == (width, height):
        return frame
    return cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)


def _sample_indices(total: int) -> List[int]:
    """Evenly spread frame numbers; the very first and last frame are skipped when there is room."""
    if total > FRAME_COUNT + 2:
        return [int(i) for i in np.linspace(0, total - 1, FRAME_COUNT + 2, dtype=int)[1:-1]]
    return [int(i) for i in np.linspace(0, total - 1, min(total, FRAME_COUNT), dtype=int)]


def _decode(jpeg: bytes) -> Optional[np.ndarray]:
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    return None if image is None else _resize(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))


def _read_frames_with_ffmpeg(video_path: str, indices: List[int]) -> List[np.ndarray]:
    """
    The given frame numbers of a video file, read with the ffmpeg command line tool. It is
    exact and, unlike cv2.VideoCapture, unaffected by the low-latency capture options this
    process sets for its live streams (those make seeking in MP4 files unreliable).
    """
    select = "+".join(f"eq(n\\,{index})" for index in sorted(set(indices)))
    try:
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-nostdin", "-i", video_path, "-vf", f"select='{select}'", "-vsync", "0",
             "-frames:v", str(len(set(indices))), "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "3", "-"],
            capture_output=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("ffmpeg could not read %s: %s", video_path, exc)
        return []
    if result.returncode != 0:
        return []
    # The output is a plain concatenation of JPEG images: split at each start-of-image marker
    frames = []
    for chunk in result.stdout.split(b"\xff\xd8")[1:]:
        frame = _decode(b"\xff\xd8" + chunk)
        if frame is not None:
            frames.append(frame)
    return frames


def _read_frames_with_opencv(video_path: str, indices: List[int]) -> List[np.ndarray]:
    capture = cv2.VideoCapture(video_path)
    frames = []
    for index in indices:
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = capture.read()
        if ok:
            frames.append(_resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
    capture.release()
    return frames


def sample_frames_from_video(video_path: str) -> List[np.ndarray]:
    """Up to FRAME_COUNT evenly spaced RGB frames of a video file (empty when it cannot be read)."""
    capture = cv2.VideoCapture(video_path)
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) if capture.isOpened() else 0
    capture.release()
    if total <= 0:
        return []
    indices = _sample_indices(total)
    return _read_frames_with_ffmpeg(video_path, indices) or _read_frames_with_opencv(video_path, indices)


def sample_frames_from_buffer(jpeg_frames: List[JpegFrame]) -> List[np.ndarray]:
    """Up to FRAME_COUNT evenly spaced RGB frames of buffered camera frames."""
    frames = [_decode(jpeg_frames[index][1]) for index in _sample_indices(len(jpeg_frames))] if jpeg_frames else []
    return [frame for frame in frames if frame is not None]


def frame_times(duration_sec: float, count: int) -> List[float]:
    """Position (seconds from the start of the clip) of each of `count` sampled frames."""
    step = duration_sec / max(1, count)
    return [round(index * step, 2) for index in range(count)]


def frame_to_base64(frame_rgb: np.ndarray) -> str:
    _, buffer = cv2.imencode(".jpg", cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return base64.b64encode(buffer).decode("ascii")


# ------------------------------------------------------------------- text shaping
def _first_sentence(value: str) -> str:
    value = re.sub(r"[*_`#>]", "", value).strip()
    value = re.sub(r"^\[[^\]]*\]\s*", "", value)  # leading "[00:00 - 02.4 sn]" time tags
    match = re.match(r"(.+?[.!?])(\s|$)", value)
    return (match.group(1) if match else value).strip()


def _stems(value: str) -> set:
    # Turkish words carry their meaning up front; suffixes vary ("takmadan" / "takmadığı")
    return {word[:5] for word in re.findall(r"\w+", value.lower()) if len(word) > 3}


def compact_summary(text: str) -> Optional[Tuple[str, str, Optional[str]]]:
    """
    Reduces a model answer to the agreed note and returns (headline, note, verdict), or None
    when the answer contains nothing usable. The prompt asks for exactly this form; the model
    does not always obey, and a long answer is of no use to an operator. `verdict` is one of
    the VERDICTS values, or None when the model gave none.
    """
    headline, details, advice, verdict = "", [], "", None
    for raw_line in text.splitlines():
        plain = re.sub(r"[*_`#>📌]", "", raw_line).strip()
        if not plain:
            continue
        lowered = plain.lower()
        if lowered.startswith("değerlendirme:"):
            answer = lowered.split(":", 1)[1].strip()
            verdict = verdict or next((value for prefix, value in VERDICTS.items() if answer.startswith(prefix)), None)
        elif lowered.startswith("özet başlık:"):
            headline = headline or _first_sentence(plain.split(":", 1)[1])
        elif lowered.startswith("öneri:"):
            advice = advice or _first_sentence(plain.split(":", 1)[1])
        elif re.match(r"^[-•]\s+", plain):
            details.append(_first_sentence(re.sub(r"^[-•]\s+", "", plain)))
        elif not headline and not lowered.endswith(":"):
            headline = _first_sentence(plain)
    if not headline:
        return None

    def repeats_headline(detail: str) -> bool:
        words = _stems(detail)
        return bool(words) and len(words & _stems(headline)) / len(words) >= 0.5

    details = [detail for detail in details if detail and not repeats_headline(detail)][:SUMMARY_MAX_DETAILS]
    lines = [f"**Özet Başlık:** {headline}"] + [f"- {detail}" for detail in details]
    if advice:
        lines.append(f"**Öneri:** {advice}")
    return headline, "\n".join(lines), verdict


def _prompt(camera_name: str, anomaly_type: str, duration_sec: float, frame_count: int, rule_context: Optional[str]) -> str:
    if rule_context:
        reason = f"Alarmın nedeni: {rule_context}"
        confirmed = "alarmın nedeni karelerde açıkça görünüyor"
    else:
        reason = "Alarmın nedeni: hareket algılayıcı olağandışı bir hareket sezdi; ne olduğunu bilmiyor."
        confirmed = ("görevlinin bakması gereken bir durum açıkça görünüyor (kavga, saldırı, düşme, kaza, hırsızlık, "
                     "zorla giriş, panik, hasar, yangın gibi)")
    return (
        f"Bir güvenlik kamerası olayının zaman sırasına dizilmiş {frame_count} karesini görüyorsun "
        f"('{camera_name}', yaklaşık {duration_sec:.0f} saniye).\n"
        f"{reason}\n\n"
        f"Güvenlik görevlisi bu notu bir bakışta okuyacak. Yalnızca şu biçimde, Türkçe yaz:\n\n"
        f"**Değerlendirme:** GERÇEK, OLAĞAN ya da BELİRSİZ sözcüklerinden yalnızca biri. "
        f"GERÇEK: {confirmed}. OLAĞAN: karelerde yalnızca gündelik, sıradan bir hareket var "
        f"(yürüyen, çalışan, konuşan insanlar gibi). BELİRSİZ: kareler karar vermeye yetmiyor.\n"
        f"**Özet Başlık:** Ne olduğunu anlatan tek kısa cümle (en fazla {HEADLINE_MAX_WORDS} kelime).\n"
        f"- Yalnızca gerekiyorsa, en fazla {SUMMARY_MAX_DETAILS} madde: görevlinin karar vermesine yarayan ve "
        f"başlıkta olmayan bir bilgi (kaç kişi, tam olarak nerede, olay sürüyor mu). Her madde tek kısa cümle.\n"
        f"**Öneri:** Görevliye emir kipinde tek kısa cümle (örnek: 'Çalışanı baret takması için uyarın.'). "
        f"Yapılacak bir şey yoksa bu satırı yazma.\n\n"
        f"KURALLAR:\n"
        f"1. Toplam {SUMMARY_MAX_WORDS} kelimeyi geçme. Başlık yeterliyse madde yazma.\n"
        f"2. Yalnızca karelerde açıkça görüneni yaz; emin olmadığın şeyi yazma, tahmin yürütme.\n"
        f"3. Başlığı başka sözlerle tekrarlama; kıyafet rengi gibi karara etkisi olmayan ayrıntı yazma; "
        f"genel güvenlik bilgisi verme.\n"
        f"4. Sistem, kural, model, skor ya da teknik terim adı (örneğin 'NO-Hardhat') geçirme.\n"
        f"5. Karelerde alarmı doğrulayan bir şey görünmüyorsa başlıkta bunu açıkça söyle."
    )


# --------------------------------------------------------------------- summarizer
class VLMSummarizer:
    """Client of the vision-language model. `available` is False when no credentials are configured."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None, model_name: Optional[str] = None):
        self.model_name = model_name or llm_config.MODEL
        api_key = api_key or llm_config.API_KEY
        base_url = base_url or llm_config.BASE_URL
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=90) if (api_key and base_url) else None

    @property
    def available(self) -> bool:
        return self.client is not None

    def summarize(
        self,
        camera_name: str,
        anomaly_type: str,
        duration_sec: float,
        video_path: Optional[str] = None,
        raw_frames: Optional[List[JpegFrame]] = None,
        rule_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Writes the note for one incident from its clip file or from buffered camera frames.
        Returns {"status": "completed" | "fallback", "summary", "headline", "verdict", "latency_sec"};
        "fallback" means no summary could be written and `summary` says why. `verdict` tells
        whether the footage shows the alarm ("confirmed"), only everyday activity ("normal"),
        or not enough to decide ("unclear"); None when the model gave none.
        """
        started = time.perf_counter()
        try:
            frames = sample_frames_from_video(video_path) if video_path else sample_frames_from_buffer(raw_frames or [])
        except Exception as exc:
            logger.error("Frames of the incident could not be read: %s", exc)
            frames = []
        if not frames:
            return self._not_summarized(anomaly_type, "videodan kare alınamadı")
        if not self.available:
            return self._not_summarized(anomaly_type, "özet servisi kullanılamıyor")

        content: List[Dict[str, Any]] = [
            {"type": "text", "text": _prompt(camera_name, anomaly_type, duration_sec, len(frames), rule_context)}
        ]
        content += [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{frame_to_base64(frame)}"}}
            for frame in frames
        ]
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": content}],
                temperature=0.15,
                max_tokens=SUMMARY_MAX_TOKENS,
            )
        except Exception as exc:
            quota = any(marker in str(exc) for marker in ("429", "token_limit", "rate_limit"))
            logger.warning("Summary request failed: %s", exc)
            return self._not_summarized(
                anomaly_type, "özet servisinin günlük kullanım kotası doldu" if quota else "özet servisine ulaşılamadı"
            )

        answer = re.sub(r"<think>.*?</think>", "", response.choices[0].message.content or "", flags=re.DOTALL)
        compact = compact_summary(answer)
        if compact is None:
            return self._not_summarized(anomaly_type, "özet servisi boş yanıt verdi")
        headline, note, verdict = compact
        return {
            "status": "completed",
            "summary": note,
            "headline": headline,
            "verdict": verdict,
            "latency_sec": round(time.perf_counter() - started, 2),
        }

    @staticmethod
    def _not_summarized(anomaly_type: str, reason: str) -> Dict[str, Any]:
        """One honest line for when the frames could not be read or the model could not be reached."""
        note = (
            f"**Özet Başlık:** {anomaly_type}\n"
            f"- Görüntü incelenemediği için özet yazılamadı ({reason}). Videoyu izleyerek değerlendirin."
        )
        return {"status": "fallback", "summary": note, "headline": anomaly_type, "verdict": None, "latency_sec": 0.0}
