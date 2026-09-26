"""
Functional tests for ONNXBackend with dynamic shape inputs.
"""

import unittest
import numpy as np
from Object_Detection.onnx_backend import ONNXBackend


class TestONNXBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        for path in [
            "yoloe-26l-seg_decoupled_sim.onnx",
            "Object_Detection/model_repository/yoloe_detector/1/model.onnx",
            "yoloe_decoupled_sim.onnx"
        ]:
            if Path(path).is_file():
                cls.backend = ONNXBackend(path)
                return
        raise FileNotFoundError("Test için geçerli bir ONNX modeli bulunamadı.")


    def test_dynamic_classes(self):
        img = np.random.randn(1, 3, 640, 640).astype(np.float32)

        # 1 class
        txt1 = np.random.randn(1, 1, 512).astype(np.float32)
        out1 = self.backend.infer(img, txt1)
        self.assertEqual(out1.shape, (1, 5, 8400))  # 4 bbox + 1 class

        # 4 classes
        txt4 = np.random.randn(1, 4, 512).astype(np.float32)
        out4 = self.backend.infer(img, txt4)
        self.assertEqual(out4.shape, (1, 8, 8400))  # 4 bbox + 4 classes

        # 10 classes
        txt10 = np.random.randn(1, 10, 512).astype(np.float32)
        out10 = self.backend.infer(img, txt10)
        self.assertEqual(out10.shape, (1, 14, 8400))  # 4 bbox + 10 classes

    def test_dynamic_batch(self):
        # Batch = 2
        img = np.random.randn(2, 3, 640, 640).astype(np.float32)
        txt = np.random.randn(1, 3, 512).astype(np.float32)
        out = self.backend.infer(img, txt)
        self.assertEqual(out.shape, (2, 7, 8400))


if __name__ == "__main__":
    unittest.main()
