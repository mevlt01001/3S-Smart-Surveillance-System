"""
End-to-End Functional Test for YOLODetector.
"""

import unittest
from pathlib import Path
from Object_Detection import YOLODetector


class TestYOLODetectorE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image_path = "bus.jpg"
        assert Path(cls.image_path).exists(), f"{cls.image_path} bulunamadı!"
        model_file = "yoloe-26l-seg_decoupled_sim.onnx"
        if not Path(model_file).exists():
            model_file = "Object_Detection/model_repository/yoloe_detector/1/model.onnx"
        cls.detector = YOLODetector(
            model_path=model_file,
            classes=["person", "bus"],
            conf_thres=0.25,
            iou_thres=0.45,
        )


    def test_detect_person_and_bus(self):
        results = self.detector.detect(self.image_path)
        self.assertGreater(len(results), 0, "En az bir nesne tespit edilmeliydi.")

        class_names = [b.cls_name for b in results.boxes]
        self.assertIn("person", class_names)
        self.assertIn("bus", class_names)

        # High confidence check
        for b in results.boxes:
            self.assertGreaterEqual(b.conf, 0.25)
            self.assertEqual(len(b.xyxy), 4)
            # Verify coordinates are positive and valid
            self.assertGreaterEqual(b.xyxy[0], 0)
            self.assertGreaterEqual(b.xyxy[1], 0)
            self.assertGreater(b.xyxy[2], b.xyxy[0])
            self.assertGreater(b.xyxy[3], b.xyxy[1])

    def test_dynamic_class_switch(self):
        # Dynamically switch prompt to "shoes" without reloading the model
        self.detector.set_classes(["shoes"])
        results = self.detector.detect(self.image_path, conf_thres=0.20)
        self.assertGreater(len(results), 0, "Ayakkabı tespiti yapılabilmeliydi.")
        for b in results.boxes:
            self.assertEqual(b.cls_name, "shoes")

    def test_temporary_class_override(self):
        # Override classes for this single call only
        results = self.detector.detect(self.image_path, classes=["bus"], conf_thres=0.30)
        for b in results.boxes:
            self.assertEqual(b.cls_name, "bus")
        # Ensure default classes remained unchanged
        self.assertEqual(self.detector.get_classes(), ["shoes"])

    def test_plot_and_save(self):
        results = self.detector.detect(self.image_path, classes=["person", "bus"])
        out_file = Path("Object_Detection/tests/test_output.jpg")
        saved_path = results.save(out_file)
        self.assertTrue(Path(saved_path).is_file())
        self.assertGreater(Path(saved_path).stat().st_size, 1000)
        out_file.unlink()  # Clean up test output

    def test_backend_auto_fallback(self):
        # Auto backend should automatically fall back to local ONNX when Triton is offline
        # (an unreachable address makes "Triton is offline" true even on a machine where Triton runs)
        auto_detector = YOLODetector(
            model_path="yoloe-26l-seg_decoupled_sim.onnx",
            classes=["bus"],
            backend="auto",
            triton_url="127.0.0.1:1",
        )
        self.assertEqual(auto_detector.backend_type, "onnx")
        res = auto_detector.detect(self.image_path)
        self.assertGreater(len(res), 0)

    def test_explicit_triton_offline_raises(self):
        # When explicit backend='triton' is requested but server is offline, it should raise ConnectionError with clear instructions
        with self.assertRaises(ConnectionError) as ctx:
            YOLODetector(
                backend="triton",
                triton_url="localhost:9999",
                classes=["bus"],
            )
        self.assertIn("NVIDIA Triton sunucusuna", str(ctx.exception))



if __name__ == "__main__":
    unittest.main()
