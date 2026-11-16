import hashlib
import io
from pathlib import Path
import tarfile

import pytest

from scripts import download_runtime as runtime


def bundle(tmp_path, monkeypatch, members=None):
    content = b"runtime fixture"
    monkeypatch.setattr(runtime, "FILES", {"corpus.json": (len(content), hashlib.sha256(content).hexdigest())})
    archive = tmp_path / "runtime.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, kind in members or [("data/corpus.json", tarfile.REGTYPE)]:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.size = len(content) if kind == tarfile.REGTYPE else 0
            info.linkname = "/tmp/elsewhere" if kind == tarfile.SYMTYPE else ""
            tar.addfile(info, io.BytesIO(content) if info.size else None)
    monkeypatch.setattr(runtime, "ARCHIVE_SHA256", runtime.digest(archive))
    return archive


def test_verified_install(tmp_path, monkeypatch):
    archive = bundle(tmp_path, monkeypatch)
    runtime.install(archive, tmp_path / "checkout")
    assert (tmp_path / "checkout/data/corpus.json").read_bytes() == b"runtime fixture"


def test_existing_data_is_preserved(tmp_path, monkeypatch):
    archive = bundle(tmp_path, monkeypatch)
    data = tmp_path / "checkout/data"
    data.mkdir(parents=True)
    (data / "corpus.json").write_text("mine")
    with pytest.raises(ValueError, match="existing runtime"):
        runtime.install(archive, data.parent)
    assert (data / "corpus.json").read_text() == "mine"


def test_corrupt_archive_writes_nothing(tmp_path, monkeypatch):
    archive = bundle(tmp_path, monkeypatch)
    archive.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="SHA-256"):
        runtime.install(archive, tmp_path / "checkout")
    assert not (tmp_path / "checkout/data").exists()


@pytest.mark.parametrize("members", [
    [("../corpus.json", tarfile.REGTYPE)],
    [("data/corpus.json", tarfile.SYMTYPE)],
    [("data/corpus.json", tarfile.REGTYPE)] * 2,
])
def test_unsafe_members_rejected(tmp_path, monkeypatch, members):
    archive = bundle(tmp_path, monkeypatch, members)
    with pytest.raises(ValueError):
        runtime.install(archive, tmp_path / "checkout")
    assert not (tmp_path / "checkout/data").exists()


def test_file_checksum_checked_before_install(tmp_path, monkeypatch):
    archive = bundle(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "FILES", {"corpus.json": (15, "bad")})
    with pytest.raises(ValueError, match="checksum"):
        runtime.install(archive, tmp_path / "checkout")
    assert not (tmp_path / "checkout/data").exists()


def test_symlink_destination_rejected(tmp_path, monkeypatch):
    archive = bundle(tmp_path, monkeypatch)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "data").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(ValueError, match="symlink"):
        runtime.install(archive, checkout)
