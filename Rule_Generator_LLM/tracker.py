"""
Object tracker: gives the detections of consecutive frames of one camera a stable identity.

A detector answers "what is in this frame"; rules need "is this the same object as a moment
ago". Without that, a detection that flickers for a single frame raises an alarm, an object
the detector misses for a frame "disappears", and waiting time can only be measured for a
zone as a whole. The tracker turns detections into tracks:

- a detection is matched to the track of the same class it overlaps most (or, for small
  fast objects that no longer overlap, the nearest one);
- a track is *confirmed* once it was seen on CONFIRM_HITS frames, so a one-frame false
  detection never reaches the rules;
- a confirmed track the detector misses keeps being reported at its last position for
  COAST_SEC (*coasting*), so a missed frame does not make an object vanish;
- a track that stays unseen for FORGET_SEC is dropped and its identity is never reused.

It is deliberately simple (no motion model, no appearance features): cameras here are fixed
and evaluated several times per second, where overlap between consecutive frames is enough.
"""

import itertools
import math
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

CONFIRM_HITS = 2      # frames an object must be seen on before rules may react to it
COAST_SEC = 0.8       # how long a missed object is assumed to be where it was last seen
FORGET_SEC = 2.0      # unseen for this long: the track ends
MATCH_IOU = 0.15      # overlap from which two boxes are taken for the same object
NEAR_DIAGONALS = 1.0  # without overlap: the same object if it moved less than this many box diagonals


@dataclass
class TrackedBox:
    """A detection with its identity. Has the fields the rule evaluator reads from a detection."""
    xyxy: List[int]
    conf: float
    cls_name: str
    track_id: int
    confirmed: bool       # seen often enough to be taken for a real object
    coasting: bool        # not detected on this frame; reported at its last known position
    age_sec: float        # time since the object was first seen

    @property
    def center(self) -> Tuple[float, float]:
        return (self.xyxy[0] + self.xyxy[2]) / 2.0, (self.xyxy[1] + self.xyxy[3]) / 2.0

    @property
    def area(self) -> float:
        return max(0, self.xyxy[2] - self.xyxy[0]) * max(0, self.xyxy[3] - self.xyxy[1])


@dataclass
class _Track:
    track_id: int
    cls_name: str
    xyxy: List[int]
    conf: float
    first_seen: float
    last_seen: float
    hits: int = 1

    def box(self, now: float, coasting: bool) -> TrackedBox:
        return TrackedBox(
            xyxy=list(self.xyxy), conf=self.conf, cls_name=self.cls_name, track_id=self.track_id,
            confirmed=self.hits >= CONFIRM_HITS, coasting=coasting, age_sec=now - self.first_seen,
        )


def _iou(a: List[int], b: List[int]) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    intersection = width * height
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.0


def _similarity(track_box: List[int], detection_box: List[int]) -> float:
    """
    How likely the two boxes are the same object, 0 when they cannot be. Overlap always beats
    mere nearness: overlapping boxes score above 1, near ones below.
    """
    overlap = _iou(track_box, detection_box)
    if overlap >= MATCH_IOU:
        return 1.0 + overlap
    diagonal = math.hypot(track_box[2] - track_box[0], track_box[3] - track_box[1])
    reach = NEAR_DIAGONALS * max(diagonal, 1.0)
    distance = math.hypot(
        (track_box[0] + track_box[2] - detection_box[0] - detection_box[2]) / 2.0,
        (track_box[1] + track_box[3] - detection_box[1] - detection_box[3]) / 2.0,
    )
    return 1.0 - distance / reach if distance < reach else 0.0


class ObjectTracker:
    """Tracks the objects of one camera as seen by one detector. Not thread-safe: one caller."""

    def __init__(self) -> None:
        self._tracks: Dict[int, _Track] = {}
        self._ids = itertools.count(1)
        self.last_update = 0.0

    def update(self, detections: Iterable[Any], now: Optional[float] = None) -> List[TrackedBox]:
        """
        Takes the detections of a new frame (objects with `xyxy`, `conf`, `cls_name`) and
        returns every object believed to be in view: the detections of this frame with their
        identity, followed by the confirmed objects that were missed on this frame (coasting).
        """
        now = time.time() if now is None else now
        self.last_update = now
        detections = list(detections)

        # Best pairs first; every track and every detection is used at most once
        pairs = sorted(
            ((score, track_id, index)
             for track_id, track in self._tracks.items()
             for index, detection in enumerate(detections)
             if track.cls_name == detection.cls_name
             and (score := _similarity(track.xyxy, detection.xyxy)) > 0.0),
            reverse=True,
        )
        track_of: Dict[int, _Track] = {}
        matched_tracks = set()
        for _, track_id, index in pairs:
            if track_id in matched_tracks or index in track_of:
                continue
            matched_tracks.add(track_id)
            track = track_of[index] = self._tracks[track_id]
            detection = detections[index]
            track.xyxy, track.conf, track.last_seen = list(detection.xyxy), float(detection.conf), now
            track.hits += 1

        for index, detection in enumerate(detections):
            if index not in track_of:
                track = track_of[index] = _Track(
                    next(self._ids), detection.cls_name, list(detection.xyxy), float(detection.conf), now, now
                )
                self._tracks[track.track_id] = track

        boxes = [track_of[index].box(now, coasting=False) for index in range(len(detections))]
        for track_id, track in list(self._tracks.items()):
            unseen = now - track.last_seen
            if unseen > FORGET_SEC or (unseen > 0 and track.hits < CONFIRM_HITS):
                del self._tracks[track_id]  # gone, or a single detection that did not come back
            elif 0 < unseen <= COAST_SEC:
                boxes.append(track.box(now, coasting=True))
        return boxes
