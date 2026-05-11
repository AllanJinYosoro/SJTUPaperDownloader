# Captcha model

Place the jAccount captcha ONNX model here:

```text
models/jaccount_resnet.onnx
```

The local service loads this file through `CAPTCHA_MODEL_PATH`. The expected
input defaults are grayscale `1 x 1 x 40 x 100`, matching
LightQuantumArchive/jaccount-captcha-solver's `nn_model.onnx`. The decoder
accepts either multi-head character logits, sequence logits, or decoded
character indexes. If the chosen model uses a different image size or alphabet,
set these in `.env`:

```text
CAPTCHA_MODEL_PATH=models/jaccount_resnet.onnx
CAPTCHA_WIDTH=100
CAPTCHA_HEIGHT=40
CAPTCHA_CHARSET=abcdefghijklmnopqrstuvwxyz
```

https://github.com/LightQuantumArchive/jaccount-captcha-solver/releases/download/v2.0/nn_model.onnx
