# PaperDownloader

PaperDownloader is a Chrome extension plus a local Playwright service. The
extension adds an `SJTU PDF` button to Google Scholar results and now starts the
local service automatically through Chrome Native Messaging when needed.

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
PORT=8765
CAPTCHA_MODEL_PATH=models/nn_model.onnx
CAPTCHA_WIDTH=110
CAPTCHA_HEIGHT=40
CAPTCHA_CHARSET=abcdefghijklmnopqrstuvwxyz
```

Put the jAccount ONNX captcha model at `models/nn_model.onnx`, or set
`CAPTCHA_MODEL_PATH` to the model location. The service performs CPU inference
with `onnxruntime`.

## One-Time Native Host Install

Build and register the native host:

```bash
powershell -ExecutionPolicy Bypass -File .\scripts\install_native_host.ps1
```

The install script compiles `scripts/paperdownloader_native_host.cs` into
`dist/paperdownloader-host.exe`, then writes the Chrome Native Messaging
registration for the fixed extension ID
`hnmnojlkimfjgmeelnghlegofogpohoi` and points it at
`dist/paperdownloader-host.exe`.

## Load the Extension

1. Open `chrome://extensions`.
2. Enable developer mode.
3. Load unpacked extension and select this repository's `extension/` directory.
4. Reload the extension after running the native-host install script.
5. Open Google Scholar search results and click `SJTU PDF`.

Downloads run headless by default. The popup can switch to a visible
debug browser window. Uncheck the background option and click **Save** to show
the browser on the next download. **Check & Start** verifies the local service;
the browser opens when you click **SJTU PDF**.

Each download reports its current stage on Scholar and records timestamps,
elapsed time, and failures in `.debug/<task_id>/workflow.log`. Failures also save
`failure.png` with input fields masked, when the page is still available.
The error includes the failed stage and diagnostic directory, including for
timeouts. Account credentials are redacted from error messages.

The downloader uses its own `.browser-profile/`, so your normal Chrome login
is not automatically shared. Use the visible mode to inspect institution login
when needed. BrowserSkill can separately test the normal signed-in Chrome flow.

## Manual Fallback

For local debugging, you can still start the HTTP service yourself:

```bash
uv run python -m paperdownloader.cli
```

## Notes

- Browser automation uses a persistent profile in `.browser-profile/`, so SJTU
  and EBSCO login state can be reused.
- Downloads are accepted into the OS default downloads directory, currently
  `~/Downloads` unless `DOWNLOAD_DIR` is set. PDFs use the paper title as their
  filename: invalid Windows characters are removed, long names are truncated
  without splitting Unicode characters, and `.pdf` is retained. Empty names use
  `paper.pdf`; reserved device names are prefixed with `_`. Existing files are
  preserved with `-1`, `-2`, etc. added before `.pdf`.
- If Primo returns no result, if the first result title is too different, or if
  ExLibris has no EBSCOhost source, the extension surfaces the service error.
