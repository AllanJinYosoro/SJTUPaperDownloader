import unittest

import cv2
import numpy as np

from paperdownloader.captcha import JAccountCaptchaSolver
from paperdownloader.config import Settings


class CaptchaTests(unittest.TestCase):
    def test_binary_model_input_and_repeated_character_heads(self):
        solver = JAccountCaptchaSolver(Settings(_env_file=None))
        pixels = np.full((40, 110), 156, dtype=np.uint8)
        pixels[:, :55] = 155
        ok, encoded = cv2.imencode(".png", pixels)
        self.assertTrue(ok)
        actual = solver._preprocess(encoded.tobytes())
        self.assertEqual(actual.shape, (1, 1, 40, 110))
        np.testing.assert_array_equal(actual[0, 0], (pixels >= 156).astype(np.float32))
        heads = []
        for index in [0, 0, 1, 2, 26]:
            logits = np.zeros((1, 27))
            logits[0, index] = 1
            heads.append(logits)
        self.assertEqual(solver._decode(heads), "aabc")
