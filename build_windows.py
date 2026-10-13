"""Build the portable Windows app and its notices/source release assets."""
from __future__ import annotations
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from branding import VERSION
from release_packaging import (NODE_VERSION, ensure_sources, package_release, prepare_node,
                               sha256, verify_environment, verify_materials)


def main():
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("Run Build-Windows.cmd with 64-bit Python on Windows. PyInstaller cannot cross-compile the GUI executable.")
    root = Path(__file__).resolve().parent
    verify_environment(root)
    verify_materials(root)
    print("Preparing verified source archives and license material…", flush=True)
    ensure_sources(root)
    print(f"Preparing official Node.js {NODE_VERSION}…", flush=True)
    node = prepare_node(root)
    ffmpeg = root / "tools/ffmpeg.exe"
    shutil.copyfile(root / "runtime_bin/ffmpeg.exe", ffmpeg)
    node_version = subprocess.check_output([str(node), "--version"], text=True).strip()
    if node_version != f"v{NODE_VERSION}":
        raise RuntimeError("Unexpected Node runtime version.")
    ffmpeg_version = subprocess.check_output([str(ffmpeg), "-version"], text=True)
    ffmpeg_license = subprocess.check_output([str(ffmpeg), "-L"], text=True, stderr=subprocess.STDOUT)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
               "--name", "YM-DL", "--additional-hooks-dir", str(root / "hooks"),
               "--exclude-module", "imageio_ffmpeg", "--exclude-module", "release_packaging",
               "--collect-all", "yt_dlp", "--collect-all", "yt_dlp_ejs",
               "--collect-data", "ytmusicapi", "--collect-data", "certifi",
               "--collect-submodules", "mutagen", "--copy-metadata", "yt-dlp-ejs",
               "--copy-metadata", "yt-dlp", "--add-binary", f"{node};tools",
               "--icon", str(root / "assets/ym-dl.ico"), "--add-data", f"{root / 'assets'};assets",
               "--add-binary", f"{ffmpeg};tools", "app.py"]
    subprocess.run(command, cwd=root, check=True)
    output = root / "dist/YM-DL.exe"
    print("Checking the packaged interface, codecs, worker and runtimes…", flush=True)
    subprocess.run([str(output), "--self-check", str(output.parent / "self-check.json")], check=True, timeout=120)
    self_check = json.loads((output.parent / "self-check.json").read_text())
    if self_check.get("runtime") != "node" or self_check.get("version") != VERSION:
        raise RuntimeError("Frozen self-check does not match this release's runtime/version.")
    record = {"app_version": VERSION, "python": sys.version, "platform": platform.platform(),
              "node": node_version, "node_sha256": sha256(node), "ffmpeg": ffmpeg_version,
              "ffmpeg_license": ffmpeg_license, "ffmpeg_sha256": sha256(ffmpeg),
              "ffmpeg_build": json.loads((root / "runtime_bin/ffmpeg-build.json").read_text()),
              "executable_sha256": sha256(output), "self_check": self_check}
    (output.parent / "build-info.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    with (output.parent / "dependencies.txt").open("w", encoding="utf-8") as stream:
        subprocess.run([sys.executable, "-m", "pip", "freeze"], check=True, stdout=stream)
    print("Creating the Windows download ZIP, full source ZIP and checksums…", flush=True)
    paths = package_release(root, output, record, root / "build/YM-DL/Analysis-00.toc", VERSION)
    print("\nBuild and checks passed. Upload these three files to the GitHub release:", flush=True)
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
