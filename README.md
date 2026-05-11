# PaperDownloader

PaperDownloader is a Chrome extension plus a local Python service. The
extension adds an `SJTU PDF` button to Google Scholar results; the local service
uses Playwright to search Shanghai Jiao Tong University Library, choose the
EBSCOhost full-text source, handle jAccount login, and trigger the PDF download.

## Setup

Install dependencies with uv:

```bash
uv sync
uv run python -m playwright install chromium
```

Create `.env` from `.env.example` and fill:

```text
Jaccount_Username=...
Jaccount_PWD=...
CAPTCHA_MODEL_PATH=models/nn_model.onnx
CAPTCHA_WIDTH=110
CAPTCHA_HEIGHT=40
CAPTCHA_CHARSET=abcdefghijklmnopqrstuvwxyz
```

Put the jAccount ONNX captcha model at `models/nn_model.onnx`, or set
`CAPTCHA_MODEL_PATH` to the model location. The service performs CPU inference
with `onnxruntime`. If your ONNX model reports a different input width, update
`CAPTCHA_WIDTH` to match the model error message.

Captcha recognition is based on the open-source jAccount captcha solver and its
pretrained ONNX model from
[LightQuantumArchive/jaccount-captcha-solver](https://github.com/LightQuantumArchive/jaccount-captcha-solver).
Thanks to the original authors and maintainers for publishing the model and
training code.

## Run

Start the local service:

```bash
uv run python -m paperdownloader.cli
```

Load `extension/` as an unpacked Chrome extension:

1. Open `chrome://extensions`.
2. Enable developer mode.
3. Load unpacked extension and select this repository's `extension/` directory.
4. Open Google Scholar search results and click `SJTU PDF` on a result.

The popup controls the local service URL and whether Playwright runs headless.
The default service URL is `http://127.0.0.1:8765`.

## Notes

- Browser automation uses a persistent profile in `.browser-profile/`, so SJTU
  and EBSCO login state can be reused.
- Downloads are accepted into the OS default downloads directory, currently
  `~/Downloads` unless `DOWNLOAD_DIR` is set.
- If Primo returns no result, if the first result title is too different, or if
  ExLibris has no EBSCOhost source, the extension surfaces the service error.
