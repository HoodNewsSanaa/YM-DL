import hashlib
import json
import zipfile
from pathlib import Path
import pytest
import release_packaging as release


class Response:
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def raise_for_status(self): pass
    def iter_content(self, size): yield self.data


class Session:
    def __init__(self, data): self.data, self.calls = data, 0
    def get(self, *args, **kwargs):
        self.calls += 1
        return Response(self.data)


def test_corrupt_download_does_not_replace_existing_input_or_leave_temporary_file(tmp_path):
    target = tmp_path / "runtime.zip"
    target.write_bytes(b"previous")
    session = Session(b"incomplete")
    with pytest.raises(RuntimeError, match="Checksum mismatch"):
        release.download_verified("https://example.test/runtime.zip", target, hashlib.sha256(b"correct").hexdigest(), session)
    assert target.read_bytes() == b"previous"
    assert list(tmp_path.iterdir()) == [target]


def test_verified_cache_avoids_network_and_invalid_cache_is_replaced(tmp_path):
    target, data = tmp_path / "runtime.zip", b"correct archive"
    digest = hashlib.sha256(data).hexdigest()
    target.write_bytes(b"bad cache")
    session = Session(data)
    release.download_verified("https://example.test/runtime.zip", target, digest, session)
    release.download_verified("https://example.test/runtime.zip", target, digest, session)
    assert target.read_bytes() == data and session.calls == 1


def test_frozen_inventory_removes_account_paths_and_rejects_uncovered_qt(tmp_path):
    binary = tmp_path / "private-directory" / "library.dll"
    binary.parent.mkdir(); binary.write_bytes(b"runtime")
    toc = tmp_path / "Analysis.toc"
    toc.write_text(repr([[("Qt6WebEngineCore.dll", str(binary), "BINARY")]]))
    inventory = release.frozen_inventory(toc)
    assert str(tmp_path) not in json.dumps(inventory)
    with pytest.raises(RuntimeError, match="Qt source coverage missing"):
        release.check_frozen_coverage(inventory)
    with pytest.raises(RuntimeError, match="OpenGL runtime"):
        release.check_frozen_coverage([{"name": "opengl32sw.dll"}])


def test_release_contains_sources_and_notices_without_private_root_files(tmp_path, monkeypatch):
    root, dist = tmp_path / "project", tmp_path / "dist"
    root.mkdir();dist.mkdir()
    for folder in ("assets", "hooks", "runtime_sources", "runtime_bin", "release_materials/licenses", "release_materials/qt-sources"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    (root / "app.py").write_text("# application source\n")
    (root / "LICENSE").write_text("project license")
    (root / "private_credentials.py").write_text("SECRET")
    (root / "cookies.txt").write_text("SECRET")
    (root / "release_materials/licenses/LICENSE.txt").write_text("supplier notice")
    (root / "release_materials/licenses/cookies.txt").write_text("SECRET")
    (root / "release_materials/qt-sources/qt.tar.gz").write_bytes(b"matching source")
    entry = {"file": "release_materials/licenses/LICENSE.txt", "sha256": release.sha256(root / "release_materials/licenses/LICENSE.txt")}
    (root / "release_materials/materials-manifest.json").write_text(json.dumps([entry]))
    (root / "release_materials/qt-source-manifest.json").write_text(json.dumps([{"file": "qt-sources/qt.tar.gz"}]))
    (root / "release_materials/python-source-manifest.json").write_text("[]")
    exe = dist / "YM-DL.exe";exe.write_bytes(b"executable fixture")
    (dist / "dependencies.txt").write_text("pinned fixture")
    (dist / "self-check.json").write_text('{"ok": true}')
    toc = tmp_path / "Analysis.toc";toc.write_text("[]")
    monkeypatch.setattr(release, "collect_package_notices", lambda *args: [])
    windows, sources, hashes = release.package_release(root, exe, {"app_version": "test"}, toc, "test")
    with zipfile.ZipFile(windows) as package:
        assert package.read("YM-DL.exe") == exe.read_bytes()
        assert package.read("licenses/LICENSE.txt") == b"supplier notice"
        assert not any("cookies" in name for name in package.namelist())
    with zipfile.ZipFile(sources) as package:
        assert package.read("app.py") == (root / "app.py").read_bytes()
        assert package.read("release_materials/qt-sources/qt.tar.gz") == b"matching source"
        assert not any("cookies" in name or "private_credentials" in name for name in package.namelist())
    assert release.sha256(windows) in hashes.read_text() and release.sha256(sources) in hashes.read_text()


def test_release_runtime_prefers_bundled_node_to_path_deno(tmp_path, monkeypatch):
    import engine
    (tmp_path / "tools").mkdir()
    suffix = ".exe" if engine.os.name == "nt" else ""
    node = tmp_path / "tools" / ("node" + suffix);node.write_bytes(b"verified node")
    monkeypatch.setattr(engine.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(engine.shutil, "which", lambda name: "unrelated-path-deno")
    assert engine.runtime_path() == ("node", str(node))
