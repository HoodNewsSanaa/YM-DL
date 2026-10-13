"""Build a portable Windows app on Windows; no FFmpeg/runtime install needed afterward."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import imageio_ffmpeg
import requests


def main():
    if sys.platform != "win32":
        raise SystemExit("Run this build on Windows. PyInstaller cannot cross-compile a Windows executable on Linux.")
    root = Path(__file__).resolve().parent
    tools = root / "tools"
    tools.mkdir(exist_ok=True)
    deno = tools / "deno.exe"
    if not deno.is_file():
        print("Downloading the official Deno runtime…", flush=True)
        url = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
        with requests.get(url, stream=True, timeout=(15, 180)) as response:
            response.raise_for_status()
            with tempfile.TemporaryFile() as archive:
                for chunk in response.iter_content(1024 * 1024):
                    archive.write(chunk)
                archive.seek(0)
                with zipfile.ZipFile(archive) as package:
                    # Extract only the intended executable, never arbitrary archive paths.
                    deno.write_bytes(package.read("deno.exe"))
    deno_version = subprocess.check_output([str(deno), "--version"], text=True).strip()
    ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
    subprocess.run([str(ffmpeg), "-version"], check=True, capture_output=True)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
               "--name", "YM-DL", "--collect-all", "yt_dlp", "--collect-all", "yt_dlp_ejs",
               "--collect-data", "ytmusicapi", "--collect-data", "certifi",
               "--collect-submodules", "mutagen", "--copy-metadata", "yt-dlp-ejs",
               "--copy-metadata", "yt-dlp", "--add-binary", f"{deno};tools",
               "--icon", str(root / "assets" / "ym-dl.ico"),
               "--add-data", f"{root / 'assets'};assets",
               "--add-binary", f"{ffmpeg};tools", "app.py"]
    # FFmpeg is stored under imageio's versioned name; ship the stable name expected at runtime.
    stable_ffmpeg = tools / "ffmpeg.exe"
    shutil.copyfile(ffmpeg, stable_ffmpeg)
    command[command.index(f"{ffmpeg};tools")] = f"{stable_ffmpeg};tools"
    subprocess.run(command, cwd=root, check=True)
    output = root / "dist" / "YM-DL.exe"
    print("Checking the packaged interface, worker, FFmpeg and JavaScript runtime…", flush=True)
    subprocess.run([str(output), "--self-check", str(output.parent / "self-check.json")], check=True, timeout=90)
    record = {"deno": deno_version, "deno_sha256": hashlib.sha256(deno.read_bytes()).hexdigest(),
              "executable_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}
    (root / "dist" / "build-info.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    with (root / "dist" / "dependencies.txt").open("w", encoding="utf-8") as handle:
        subprocess.run([sys.executable, "-m", "pip", "freeze"], cwd=root, check=True, stdout=handle)
    print(f"\nBuilt: {output}\nYou can launch or move YM-DL.exe by itself.")


if __name__ == "__main__":
    main()
