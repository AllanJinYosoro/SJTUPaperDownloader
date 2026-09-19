"""Build installable extension archives without Node or a bundler."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parents[1]
output = root / "dist"
output.mkdir(exist_ok=True)
for directory, filename in (("zotero", "sjtu-attachments.xpi"), ("extension", "sjtu-scholar.zip")):
    target = output / filename
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for path in sorted((root / directory).rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(root / directory))
    print(target)

target = output / "sjtu-paperdownloader-windows.zip"
with ZipFile(target, "w", ZIP_DEFLATED) as archive:
    for directory in ("paperdownloader", "windows", "extension", "zotero", "scripts", "examples", "tests"):
        for path in sorted((root / directory).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, path.relative_to(root))
    for name in ("README.md", "pyproject.toml", "uv.lock", ".env.example"):
        archive.write(root / name, name)
    archive.write(output / "sjtu-attachments.xpi", "dist/sjtu-attachments.xpi")
print(target)
