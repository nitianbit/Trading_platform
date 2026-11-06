"""Fingerprint the distributable working tree, including uncommitted source."""
from pathlib import Path
import hashlib
import os

ROOT=Path(__file__).resolve().parents[1]
PRIVATE={".git",".local",".claude",".codex",".cache",".impeccable",".venv","node_modules","dist","logs","__pycache__"}


def source_fingerprint(root=ROOT):
    digest=hashlib.sha256()
    paths=[]
    for directory, children, names in os.walk(root):
        children[:]=[name for name in children if name not in PRIVATE]
        paths.extend(Path(directory)/name for name in names)
    for path in sorted(paths):
        relative=path.relative_to(root)
        if set(relative.parts)&PRIVATE or not path.is_file(): continue
        if path.name.startswith(".env") and path.name!=".env.example": continue
        if path.suffix in (".log",".dump",".pyc") or path.name==".DS_Store": continue
        digest.update(relative.as_posix().encode()+b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def verify_image(image, expected):
    import subprocess
    actual=subprocess.check_output(["docker","image","inspect","--format",'{{ index .Config.Labels "io.dhk-paper.source-fingerprint" }}',image],text=True).strip()
    if actual!=expected: raise RuntimeError("Image source fingerprint mismatch for " + image + "; run scripts/build_images.py")


if __name__=="__main__": print(source_fingerprint())
