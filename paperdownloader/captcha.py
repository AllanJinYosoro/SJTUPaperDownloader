from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

from .config import Settings


class CaptchaSolverError(RuntimeError):
    pass


class JAccountCaptchaSolver:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_path = Path(settings.captcha_model_path)
        self.charset = settings.captcha_charset
        self._session: ort.InferenceSession | None = None

    def available(self) -> bool:
        return self.model_path.exists()

    def solve(self, image_bytes: bytes) -> str:
        if not self.model_path.exists():
            raise CaptchaSolverError(
                f"Captcha model not found at {self.model_path}. Put the jAccount ONNX "
                "model there or set CAPTCHA_MODEL_PATH."
            )
        session = self._get_session()
        input_name = session.get_inputs()[0].name
        outputs = session.run(None, {input_name: self._preprocess(image_bytes)})
        text = self._decode(outputs)
        if not text:
            raise CaptchaSolverError("Captcha model returned an empty prediction.")
        return text

    def _get_session(self) -> ort.InferenceSession:
        if self._session is None:
            self._session = ort.InferenceSession(
                str(self.model_path),
                providers=["CPUExecutionProvider"],
            )
        return self._session

    def _preprocess(self, image_bytes: bytes) -> np.ndarray:
        data = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise CaptchaSolverError("Could not decode captcha image.")
        image = cv2.resize(
            image,
            (self.settings.captcha_width, self.settings.captcha_height),
            interpolation=cv2.INTER_AREA,
        )
        image = image.astype(np.float32) / 255.0
        image = (image - 0.5) / 0.5
        return image[np.newaxis, np.newaxis, :, :]

    def _decode(self, output: object) -> str:
        if isinstance(output, list) and len(output) > 1:
            return self._decode_multi_head(output)

        logits = np.asarray(output[0] if isinstance(output, list) else output)
        if logits.ndim == 3:
            logits = logits[0]
        if logits.ndim == 2:
            indexes = logits.argmax(axis=-1)
        elif logits.ndim == 1:
            indexes = logits.astype(np.int64)
        else:
            raise CaptchaSolverError(f"Unsupported captcha output shape: {logits.shape}")

        chars: list[str] = []
        blank_index = len(self.charset)
        previous = None
        for raw_index in indexes.tolist():
            index = int(raw_index)
            if index == previous:
                continue
            previous = index
            if index == blank_index:
                continue
            if 0 <= index < len(self.charset):
                chars.append(self.charset[index])
        return "".join(chars)

    def _decode_multi_head(self, outputs: list[object]) -> str:
        chars: list[str] = []
        for raw_logits in outputs:
            logits = np.asarray(raw_logits)
            index = int(logits.reshape(-1).argmax())
            if 0 <= index < len(self.charset):
                chars.append(self.charset[index])
        return "".join(chars)
