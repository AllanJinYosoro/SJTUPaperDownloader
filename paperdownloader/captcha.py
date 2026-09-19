"""CPU inference for LightQuantumArchive/jaccount-captcha-solver v2.0.

The model takes binary 0/1 pixels, not normalized grayscale; outputs are
independent character heads, so repeated letters must not be collapsed.
"""
from functools import lru_cache
from io import BytesIO
from pathlib import Path


@lru_cache(maxsize=1)
def session(path: str):
    import onnxruntime
    options = onnxruntime.SessionOptions()
    options.log_severity_level = 3
    return onnxruntime.InferenceSession(path, sess_options=options, providers=["CPUExecutionProvider"])


def solve(image_bytes: bytes, model: Path) -> str:
    import numpy as np
    from PIL import Image
    inference = session(str(model.resolve()))
    spec = inference.get_inputs()[0]
    image = Image.open(BytesIO(image_bytes)).convert("L")
    height, width = spec.shape[-2:]
    if isinstance(height, int) and isinstance(width, int) and image.size != (width, height):
        image = image.resize((width, height), Image.Resampling.NEAREST)
    pixels = np.asarray(image, dtype=np.uint8)
    inputs = (pixels >= 156).astype(np.float32)[None, None, :, :]
    outputs = inference.run(None, {spec.name: inputs})
    if len(outputs) not in (4, 5) or any(out.shape not in ((1, 26), (1, 27)) for out in outputs):
        raise ValueError("验证码模型输出格式不支持，请使用指定的 v2.0 模型")
    indexes = [int(out.argmax(axis=1)[0]) for out in outputs]
    text = "".join(chr(ord("a") + index) for index in indexes if index < 26)
    if len(text) not in (4, 5):
        raise ValueError("验证码识别长度异常")
    return text
