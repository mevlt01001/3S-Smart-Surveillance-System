"""
Functional tests for preprocessing and postprocessing utilities.
"""

import unittest
import numpy as np
import cv2
from Object_Detection.utils import (
    letterbox,
    preprocess_image,
    scale_coords,
    DetectionBox,
    DetectionResult,
)


class TestUtils(unittest.TestCase):
    def test_letterbox(self):
        # Test rectangular image letterbox
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        lb_img, r, pad = letterbox(img, new_shape=(640, 640))
        self.assertEqual(lb_img.shape, (640, 640, 3))
        self.assertAlmostEqual(r, 1.0)
        self.assertEqual(pad, (0.0, 80.0))

    def test_preprocess_image_array(self):
        img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        tensor, orig_img, (h0, w0) = preprocess_image(img, imgsz=640)
        self.assertEqual(tensor.shape, (1, 3, 640, 640))
        self.assertEqual(tensor.dtype, np.float32)
        self.assertEqual((h0, w0), (1080, 1920))

    def test_detection_result_plot_and_dict(self):
        dummy_img = np.zeros((300, 300, 3), dtype=np.uint8)
        boxes = [
            DetectionBox(xyxy=[10, 20, 100, 150], conf=0.85, cls_id=0, cls_name="person"),
            DetectionBox(xyxy=[150, 160, 250, 280], conf=0.72, cls_id=1, cls_name="car"),
        ]
        res = DetectionResult(orig_img=dummy_img, boxes=boxes, classes=["person", "car"])
        self.assertEqual(len(res), 2)

        data = res.to_dict()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["class_name"], "person")
        self.assertEqual(data[0]["confidence"], 0.85)

        plotted = res.plot()
        self.assertEqual(plotted.shape, (300, 300, 3))


if __name__ == "__main__":
    unittest.main()
