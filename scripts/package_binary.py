"""Build a self-contained UTM Connector archive for the current OS."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
UI = SRC / "utm_connector" / "ui"
CONFIG = ROOT / "config" / "utm-connector.example.json"
sys.path.insert(0, str(SRC))
from utm_connector import __version__  # noqa: E402


def release_platform() -> tuple[str, str, str]:
    if sys.platform.startswith("linux"):
        os_name = "linux"
    elif sys.platform == "win32":
        os_name = "windows"
    else:
        raise SystemExit("Binary packaging currently supports Linux and Windows only")

    machine = platform.machine().lower()
    architecture = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "aarch64": "arm64",
    }.get(machine, machine)
    suffix = ".exe" if os_name == "windows" else ""
    return os_name, architecture, suffix


def main() -> int:
    os_name, architecture, executable_suffix = release_platform()
    if os_name == "linux" and shutil.which("objdump") is None:
        raise SystemExit(
            "Linux binary packaging requires objdump (provided by binutils); "
            "install binutils before building"
        )
    build_dir = ROOT / "build" / "pyinstaller"
    dist_dir = ROOT / "dist" / "package"
    release_dir = ROOT / "dist" / "release"
    shutil.rmtree(build_dir, ignore_errors=True)
    shutil.rmtree(dist_dir, ignore_errors=True)
    release_dir.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--onefile",
        "--name",
        "utm-connector",
        "--paths",
        str(SRC),
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(build_dir / "work"),
        "--specpath",
        str(build_dir),
        "--hidden-import",
        "utm_connector.api",
        "--collect-all",
        "pymavlink",
        "--collect-all",
        "pyproj",
        "--collect-all",
        "shapely",
        "--collect-data",
        "certifi",
        "--add-data",
        f"{UI}{os.pathsep}utm_connector/ui",
        str(SRC / "utm_connector" / "__main__.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)

    executable = dist_dir / f"utm-connector{executable_suffix}"
    if not executable.is_file():
        raise FileNotFoundError(f"PyInstaller did not create the expected executable: {executable}")
    subprocess.run([str(executable), "--version"], cwd=ROOT, check=True)

    archive_name = f"utm-connector-{__version__}-{os_name}-{architecture}.zip"
    archive_path = release_dir / archive_name
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(executable, executable.name)
        archive.write(CONFIG, "utm-connector.example.json")
        archive.write(ROOT / "docs" / "standalone-package.md", "README.md")

    digest = hashlib.sha256()
    with archive_path.open("rb") as archive_file:
        for chunk in iter(lambda: archive_file.read(1024 * 1024), b""):
            digest.update(chunk)
    (release_dir / f"{archive_name}.sha256").write_text(
        f"{digest.hexdigest()}  {archive_name}\n", encoding="utf-8"
    )
    print(f"Created {archive_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
