"""Install the official signed universal macOS framework inside this venv only."""
import hashlib
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

URL = "https://github.com/sccn/liblsl/releases/download/v1.17.7/liblsl-1.17-Darwin-universal.pkg"
SHA256 = "b3f1a07c0f73fa60ca0beea4abece1b8465a2f5a223d4ad446dbfe725dc4a4fb"

if __name__ == "__main__":
    if platform.system() != "Darwin" or sys.prefix == sys.base_prefix:
        raise SystemExit("macOS에서 프로젝트 .venv/bin/python으로 실행하세요.")
    destination = Path(sys.prefix) / "lsl.framework"
    if not destination.exists():
        with tempfile.TemporaryDirectory(prefix="ganglion-lsl-") as directory:
            root = Path(directory)
            package = root / "liblsl.pkg"
            subprocess.run(["curl", "--fail", "--location", "--retry", "2", URL, "-o", str(package)], check=True)
            if hashlib.sha256(package.read_bytes()).hexdigest() != SHA256:
                raise SystemExit("liblsl 다운로드 해시가 일치하지 않습니다.")
            subprocess.run(["pkgutil", "--expand-full", str(package), str(root / "expanded")], check=True)
            source = root / "expanded/org.labstreaminglayer.liblsl.pkg/Payload/lsl.framework"
            # Keep the entire framework so macOS can validate its existing signature.
            shutil.copytree(source, destination, symlinks=True)
    from acquisition import lsl
    print(f"liblsl {lsl().library_version()} 준비 완료: {destination}")
