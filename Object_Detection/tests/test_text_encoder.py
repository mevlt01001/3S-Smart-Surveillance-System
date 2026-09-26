"""
Functional tests for PromptTextEncoder.
"""

import unittest
import numpy as np
import torch
from Object_Detection.text_encoder import PromptTextEncoder


class TestPromptTextEncoder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoder = PromptTextEncoder(model_or_path="yoloe-26l-seg.pt")

    def test_encode_shape(self):
        prompts = ["person", "car", "dog"]
        feats = self.encoder.encode(prompts)
        self.assertEqual(feats.shape, (1, 3, 512))
        self.assertIsInstance(feats, np.ndarray)
        self.assertEqual(feats.dtype, np.float32)

    def test_caching(self):
        self.encoder.clear_cache()
        self.assertEqual(self.encoder.cache_size, 0)
        
        prompts = ["laptop", "mouse"]
        feats1 = self.encoder.encode(prompts)
        self.assertEqual(self.encoder.cache_size, 1)

        # Second call should hit cache
        feats2 = self.encoder.encode(prompts)
        self.assertEqual(self.encoder.cache_size, 1)
        np.testing.assert_array_equal(feats1, feats2)

    def test_torch_output(self):
        prompts = ["bottle"]
        feats = self.encoder.encode(prompts, to_numpy=False)
        self.assertIsInstance(feats, torch.Tensor)
        self.assertEqual(feats.shape, (1, 1, 512))


if __name__ == "__main__":
    unittest.main()
