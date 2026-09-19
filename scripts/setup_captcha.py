"""Install the pinned optional jAccount model; an argument accepts an offline copy."""
import hashlib
import sys
from pathlib import Path
from urllib.request import urlopen

URL = "https://github.com/LightQuantumArchive/jaccount-captcha-solver/releases/download/v2.0/nn_model.onnx"
SHA256 = "07af9dfd5d3d0a59bb8677a2ec18c37e46c659d2e6450c40450a43e5c17b3137"
target = Path(__file__).resolve().parents[1] / ".state" / "nn_model.onnx"
target.parent.mkdir(exist_ok=True)
if target.exists():
    if hashlib.sha256(target.read_bytes()).hexdigest() != SHA256:
        raise SystemExit("Existing model has a different checksum; move it aside before installing.")
else:
    if len(sys.argv) > 1:
        data = Path(sys.argv[1]).read_bytes()
    else:
        with urlopen(URL, timeout=120) as response:
            data = response.read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise SystemExit("Model checksum mismatch; nothing installed.")
    temp = target.with_suffix(".part")
    temp.write_bytes(data)
    temp.replace(target)
print(f"Captcha model ready: {target}")
