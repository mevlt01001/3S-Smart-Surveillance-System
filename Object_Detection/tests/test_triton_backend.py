"""
Functional tests for TritonBackend module.
"""

import unittest
from Object_Detection.triton_backend import TritonBackend, TRITON_HTTP_AVAILABLE


class TestTritonBackend(unittest.TestCase):
    def test_triton_client_installed(self):
        self.assertTrue(TRITON_HTTP_AVAILABLE, "tritonclient[http] paketi kurulu olmalıdır.")

    def test_triton_backend_init(self):
        backend = TritonBackend(url="localhost:8000", model_name="yoloe_detector")
        self.assertEqual(backend.url, "localhost:8000")
        self.assertEqual(backend.model_name, "yoloe_detector")
        self.assertEqual(backend.protocol, "http")

    def test_triton_server_offline_graceful(self):
        # When server is not running, is_alive() should return False without raising an uncaught exception
        backend = TritonBackend(url="localhost:9999", model_name="yoloe_detector")
        self.assertFalse(backend.is_alive())
        self.assertFalse(backend.is_model_ready())


if __name__ == "__main__":
    unittest.main()
