# PaperDownloader

PaperDownloader is a Chrome extension plus a native host. The extension adds an
`SJTU PDF` button to Google Scholar results; the native host uses Playwright to
search Shanghai Jiao Tong University Library, choose the EBSCOhost full-text
source, handle jAccount login, and trigger the PDF download without exposing a
local HTTP port.

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
CAPTCHA_MODEL_PATH=models/jaccount_resnet.onnx
CAPTCHA_WIDTH=100
CAPTCHA_HEIGHT=40
CAPTCHA_CHARSET=abcdefghijklmnopqrstuvwxyz
```

Put the jAccount ONNX captcha model at `models/jaccount_resnet.onnx`, or set
`CAPTCHA_MODEL_PATH` to the model location. The native host performs CPU
inference with `onnxruntime`. If your ONNX model reports a different input
width, update `CAPTCHA_WIDTH` to match the model error message.

Captcha recognition is based on the open-source jAccount captcha solver and its
pretrained ONNX model from
[LightQuantumArchive/jaccount-captcha-solver](https://github.com/LightQuantumArchive/jaccount-captcha-solver).
Thanks to the original authors and maintainers for publishing the model and
training code.

## Chrome Extension

Load `extension/` as an unpacked Chrome extension:

1. Open `chrome://extensions`.
2. Enable developer mode.
3. Load unpacked extension and select this repository's `extension/` directory.
4. Copy the extension ID shown on the extensions page.

The popup controls:

- `Download directory`: optional local download path override.
- `Captcha model path`: optional override for the ONNX model location.
- `Run browser headless`: whether Playwright should hide the browser window.

The `Check host` button verifies that Chrome can reach the registered native
host and that the captcha model can be found.

## Native Host Registration

You no longer need to manually start a local web service. Chrome launches the
native host automatically through Native Messaging.

### Windows

Build or obtain `paperdownloader-host.exe`, then register it once:

```powershell
.\scripts\install_native_host_windows.ps1 `
  -HostPath .\dist\paperdownloader-host.exe `
  -ExtensionId <your-extension-id>
```

The script copies the executable to
`%LOCALAPPDATA%\PaperDownloader\NativeMessagingHost\`, writes
`paperdownloader.host.json`, and registers the manifest under the current user.

If you also want Microsoft Edge support, add `-Browser Both`.

## Development Notes

The native host entrypoint is:

```bash
uv run python -m paperdownloader.native_host
```

That command is mainly useful for packaging or protocol debugging; in normal
use, Chrome starts the host process for you.

## Notes

- Browser automation uses a persistent profile in `.browser-profile/`, so SJTU
  and EBSCO login state can be reused.
- Downloads are accepted into the OS default downloads directory, currently
  `~/Downloads` unless overridden in the extension popup.
- If Primo returns no result, if the first result title is too different, or if
  ExLibris has no EBSCOhost source, the extension surfaces the host error.
