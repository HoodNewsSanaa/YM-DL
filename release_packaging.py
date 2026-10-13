"""Verified runtime inputs and portable release/source packaging."""
from __future__ import annotations
import ast
import hashlib
import importlib.metadata as metadata
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
import requests

NODE_VERSION = "24.21.0"
NODE_ARCHIVE = f"node-v{NODE_VERSION}-win-x64.zip"
NODE_URL = f"https://nodejs.org/dist/v{NODE_VERSION}/{NODE_ARCHIVE}"
NODE_SHA256 = "158f7685b44de51f6c0df1d153526cbcd3e1bc739a8dfc607721cef75de9e541"
PROJECT_FILES = ("app.py", "artwork.py", "audio_profiles.py", "branding.py", "build_windows.py",
                 "engine.py", "gui.py", "messages.py", "metadata.py", "models.py", "quality.py",
                 "queue_control.py", "queue_view.py", "release_packaging.py", "selfcheck.py", "tagging.py",
                 "url_queue.py", "worker.py", "Build-Windows.cmd", "Run-Windows.cmd", "requirements.txt",
                 "requirements-release.txt", "requirements-dev.txt", "README.md", "PUBLISHING.md",
                 "TEST-RESULTS.md", "RELEASE-BUILD.md", "LICENSE")
TEST_FILES = ("conftest.py", "test_audio.py", "test_gui.py", "test_messages.py", "test_metadata.py",
              "test_quality.py", "test_queue_control.py", "test_url_queue.py", "test_release_packaging.py")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified(url, destination, expected_sha256, session=None):
    destination = Path(destination)
    if destination.is_file() and sha256(destination) == expected_sha256:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            with (session or requests).get(url, stream=True, timeout=(15, 180)) as response:
                response.raise_for_status()
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        stream.write(chunk)
        if sha256(temporary) != expected_sha256:
            raise RuntimeError(f"Checksum mismatch: {destination.name}. The download was not used.")
        temporary.replace(destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def pinned_requirements(root):
    return [line.strip().split("==", 1) for line in (Path(root) / "requirements-release.txt").read_text().splitlines()
            if line.strip() and not line.startswith("#")]


def verify_environment(root):
    for name, version in pinned_requirements(root):
        if metadata.version(name) != version:
            raise RuntimeError(f"Release requires {name}=={version}. Run Build-Windows.cmd.")


def verify_materials(root):
    root = Path(root)
    for item in json.loads((root / "release_materials/materials-manifest.json").read_text()):
        path = root / item["file"]
        if not path.is_file() or sha256(path) != item["sha256"]:
            raise RuntimeError(f"Release input missing or changed: {item['file']}. Re-extract the project ZIP.")
    record = json.loads((root / "runtime_bin/ffmpeg-build.json").read_text())
    checks = {"runtime_bin/ffmpeg.exe": record["executable_sha256"],
              "runtime_sources/build_ffmpeg.sh": record["recipe_sha256"]}
    checks.update({f"runtime_sources/{name}": digest for name, digest in record["source_archives"].items()})
    for name, digest in checks.items():
        if sha256(root / name) != digest:
            raise RuntimeError(f"Runtime/source checksum mismatch: {name}")


def ensure_sources(root):
    root = Path(root)
    for name in ("qt-source-manifest.json", "python-source-manifest.json"):
        for item in json.loads((root / "release_materials" / name).read_text()):
            download_verified(item["url"], root / "release_materials" / item["file"], item["sha256"])


def prepare_node(root):
    root = Path(root)
    archive = download_verified(NODE_URL, root / ".release-cache" / NODE_ARCHIVE, NODE_SHA256)
    with zipfile.ZipFile(archive) as package:
        prefix = f"node-v{NODE_VERSION}-win-x64/"
        runtime, text = package.read(prefix + "node.exe"), package.read(prefix + "LICENSE")
    license_file = root / "release_materials/licenses/Node-24.21.0/LICENSE.txt"
    if hashlib.sha256(text).hexdigest() != sha256(license_file):
        raise RuntimeError("Node's license does not match the verified upstream archive.")
    tools = root / "tools"
    tools.mkdir(exist_ok=True)
    (tools / "node.exe").write_bytes(runtime)
    return tools / "node.exe"


def collect_package_notices(root, output):
    output = Path(output)
    records = []
    for name, version in pinned_requirements(root):
        distribution, copied = metadata.distribution(name), []
        for file in distribution.files or []:
            path = Path(str(file))
            if path.is_absolute() or ".." in path.parts:
                continue
            if path.suffix.lower() in {".py", ".pyc", ".pyd", ".dll", ".exe", ".so"}:
                continue
            if not path.name.lower().startswith(("license", "licence", "copying", "notice", "copyright", "authors")):
                continue
            source = Path(distribution.locate_file(file))
            if source.is_file():
                target = output / "licenses/python" / name / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                copied.append(str(target.relative_to(output)).replace("\\", "/"))
        if name.lower().replace("_", "-") in {"pyside6-essentials", "shiboken6"}:
            # Some platform wheels omit even the commercial reference file.
            # Use the exact upstream tag's public text for our GPLv3 route.
            if version != "6.12.0":
                raise RuntimeError("Qt license/source material must be updated for this version.")
            public_text = output / "licenses/Qt-6.12.0/pyside-setup/LICENSES/GPL-3.0-only.txt"
            if not public_text.is_file():
                raise RuntimeError("Exact upstream Qt for Python GPLv3 text is missing.")
            copied.append(str(public_text.relative_to(output)).replace("\\", "/"))
        if not copied:
            raise RuntimeError(f"No dependency license text found for {name}.")
        info = distribution.metadata
        records.append({"name": name, "version": version, "license": info.get("License-Expression") or info.get("License"),
                        "notices": copied, "supplier_urls": info.get_all("Project-URL", [])})
    candidates = [Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE",
                  Path(sys.base_prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "LICENSE.txt"]
    license_file = next((p for p in candidates if p.is_file()), None)
    if license_file is None:
        raise RuntimeError("Python runtime LICENSE.txt not found; install official Windows Python.")
    target = output / "licenses/Python/LICENSE.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(license_file, target)
    return records


def frozen_inventory(toc):
    values, records = ast.literal_eval(Path(toc).read_text(encoding="utf-8")), {}
    def visit(value):
        if not isinstance(value, (tuple, list)):
            return
        if len(value) == 3 and all(isinstance(v, str) for v in value) and value[2] in {"BINARY", "EXTENSION", "DATA", "PYMODULE"}:
            name, source, kind = value
            if Path(source).is_file():
                records[(name, kind)] = {"name": name, "kind": kind, "sha256": sha256(source)}
        else:
            for item in value:
                visit(item)
    visit(values)
    return [records[k] for k in sorted(records)]


def check_frozen_coverage(inventory):
    allowed_qt = {"core", "gui", "widgets", "svg", "svgwidgets", "network", "opengl", "openglwidgets", "printsupport", "dbus", "concurrent", "xml", "sql", "test", "shadertools"}
    for entry in inventory:
        leaf = Path(entry["name"]).name.lower()
        if any(s in leaf for s in ("opengl32sw", "libegl", "libglesv2")):
            raise RuntimeError("Unexpected optional OpenGL runtime collected; add source/notice coverage before packaging.")
        if leaf.startswith("qt6") and leaf.endswith(".dll") and leaf[3:-4] not in allowed_qt:
            raise RuntimeError(f"Qt source coverage missing for {leaf}.")


def zip_tree(directory, destination):
    directory, destination = Path(directory), Path(destination)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as package:
            for path in sorted(directory.rglob("*")):
                if path.is_file():
                    package.write(path, path.relative_to(directory))
        with zipfile.ZipFile(temporary) as package:
            if package.testzip() is not None:
                raise RuntimeError("Release ZIP verification failed.")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def package_release(root, executable, build_info, analysis_toc, version):
    root, executable = Path(root), Path(executable)
    output = executable.parent
    release_zip, sources_zip = [output / f"YM-DL-{version}-{suffix}.zip" for suffix in ("Windows-x64", "Sources")]
    inventory = frozen_inventory(analysis_toc)
    check_frozen_coverage(inventory)
    with tempfile.TemporaryDirectory(dir=output, prefix="release-") as temp:
        release, sources = Path(temp) / "release", Path(temp) / "sources"
        release.mkdir(); sources.mkdir()
        shutil.copyfile(executable, release / "YM-DL.exe")
        shutil.copyfile(root / "LICENSE", release / "LICENSE")
        material_entries = json.loads((root / "release_materials/materials-manifest.json").read_text())
        for item in material_entries:
            prefix = "release_materials/licenses/"
            if item["file"].startswith(prefix):
                target = release / "licenses" / item["file"][len(prefix):]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / item["file"], target)
        record = dict(build_info, packages=collect_package_notices(root, release), frozen_files=inventory)
        for file in ("dependencies.txt", "self-check.json"):
            shutil.copyfile(output / file, release / file)
        (release / "build-info.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        (release / "THIRD-PARTY-NOTICES.txt").write_text(
            "YM-DL: GNU GPLv3; see LICENSE. Third-party components retain their own terms.\n"
            "Complete collected texts and Qt attribution records are under licenses/.\n"
            "FFmpeg 9.0.2: LGPLv3-or-later, with LAME 3.100 and Opus 1.5.2.\n"
            f"Node.js {NODE_VERSION}: complete LICENSE from the verified official archive.\n"
            "Qt/PySide/Shiboken 6.12.0: distributed using their GPLv3 option.\n"
            "PyInstaller has a bootloader distribution exception; see its COPYING.txt.\n"
            "build-info.json lists package notices, versions and frozen file checksums.\n"
            "The package inventory also includes build tooling for provenance.\n"
            f"Matching app, FFmpeg/library and Qt sources: {sources_zip.name}.\n"
            "Download that companion source asset from the same GitHub release.\n", encoding="utf-8")
        # Only known project inputs: never account data, media, caches or a venv.
        for name in PROJECT_FILES:
            file = root / name
            if file.is_file():
                shutil.copyfile(file, sources / file.name)
        shutil.copyfile(root / "LICENSE", sources / "LICENSE")
        for folder in ("assets", "hooks"):
            shutil.copytree(root / folder, sources / folder, ignore=shutil.ignore_patterns("build-*", "__pycache__", "*.pyc"))
        for name in TEST_FILES:
            path = root / "tests" / name
            if path.is_file():
                (sources / "tests").mkdir(exist_ok=True)
                shutil.copyfile(path, sources / "tests" / name)
        # Only manifest-listed material and verified source archives enter the ZIP.
        items = list(material_entries)
        for name in ("qt-source-manifest.json", "python-source-manifest.json"):
            items += [{"file": "release_materials/" + item["file"]} for item in json.loads((root / "release_materials" / name).read_text())]
        for item in items:
            dest = sources / item["file"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / item["file"], dest)
        (sources / "release_materials").mkdir(exist_ok=True)
        shutil.copyfile(root / "release_materials/materials-manifest.json", sources / "release_materials/materials-manifest.json")
        references = (
            "Repository: https://github.com/HoodNewsSanaa/YM-DL\n"
            f"Exact app files for this build are in {sources_zip.name}.\n"
            "FFmpeg/LAME/Opus source archives and an unmodified-source recipe: runtime_sources/.\n"
            "FFmpeg compiler/package digests: runtime_bin/ffmpeg-build.json.\n"
            "Qt and PySide sources, URLs and digests: release_materials/qt-source-manifest.json.\n"
            "Mutagen/certifi source archives: release_materials/python-sources/.\n"
            "Qt archives include build instructions; PySide setup.py builds bindings against Qt.\n"
            f"Python source: https://www.python.org/ftp/python/{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}/Python-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}.tar.xz\n"
            f"Node source: https://nodejs.org/dist/v{NODE_VERSION}/node-v{NODE_VERSION}.tar.xz\n"
            "The Windows build uses pinned PyPI wheels, not a claim of bit-for-bit reproduction of upstream Qt/Node/Python binaries.\n")
        for folder in (release, sources):
            (folder / "SOURCE-REFERENCES.txt").write_text(references, encoding="utf-8")
        (sources / "build-info.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        (release / "README.txt").write_text("Extract this ZIP and double-click YM-DL.exe. No Python, FFmpeg or Node installation needed.\nKeep the notices with copies you distribute.\n", encoding="utf-8")
        zip_tree(sources, sources_zip)
        zip_tree(release, release_zip)
    checksums = output / f"YM-DL-{version}-SHA256SUMS.txt"
    checksums.write_text("".join(f"{sha256(p)}  {p.name}\n" for p in (release_zip, sources_zip)), encoding="utf-8")
    return release_zip, sources_zip, checksums
