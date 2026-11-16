"""Install the published Django runtime without training or database writes."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import tarfile
import tempfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
URL = "https://github.com/codebanditssss/repocortex/releases/download/runtime-django-f24f38c6/repocortex-django-runtime.tar.gz"
ARCHIVE_SHA256 = "6c240fe0e706b4b4d5ebaf58769dc7e1acbf91d2c9c6fa1739e5c604bb79b747"
FILES = {
    "corpus.json": (47561915, "3d5fcf21b9cfdd454d585e6bd6a7ad61f633e9693646e89f90536f48778052c8"),
    "embeddings.npz": (19824396, "e956b93c4bee5c5482fd2ba984276e7b838637d8a90cd8f081275b8570ba1d24"),
    "learned_state.json": (1217735, "8f5e45ebed9e4cc167b7f92e6f9d4856d0e485b59591d3f61e4fcc9c99e90cb1"),
    "learned_state.npz": (7338324, "0f5bb7d8c79d10c025fa7d4d74e933e97696eff1042ae107108251205c6a4693"),
    "dataset.json": (3161416, "eee50894a9fad293537fb41df531b106699f90164a0ced28dc996c519d3b3d49"),
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_destination(root: Path) -> Path:
    data = root / "data"
    if data.is_symlink() or (data.exists() and not data.is_dir()):
        raise ValueError("data must be a real directory, not a symlink or file")
    occupied = [name for name in FILES if (data / name).exists() or (data / name).is_symlink()]
    if occupied:
        raise ValueError("existing runtime files; use a fresh checkout: " + ", ".join(occupied))
    return data


def install(archive: Path, root: Path) -> None:
    data = check_destination(root)
    if digest(archive) != ARCHIVE_SHA256:
        raise ValueError("archive SHA-256 does not match the published snapshot")
    # Validate every member before installing anything. Never use extractall:
    # archive paths, links, devices and duplicate members are not accepted.
    with tempfile.TemporaryDirectory(prefix="repocortex-runtime-") as temporary:
        staging = Path(temporary)
        with tarfile.open(archive, "r:gz") as bundle:
            members = bundle.getmembers()
            expected = {"data/" + name for name in FILES}
            if len(members) != len(expected) or {m.name for m in members} != expected:
                raise ValueError("archive must contain exactly the five runtime files")
            for member in members:
                name = member.name.removeprefix("data/")
                size, sha = FILES[name]
                if not member.isfile() or member.size != size:
                    raise ValueError("invalid runtime member: " + member.name)
                with bundle.extractfile(member) as source, (staging / name).open("wb") as target:
                    shutil.copyfileobj(source, target)
                if digest(staging / name) != sha:
                    raise ValueError("runtime file checksum mismatch: " + name)
        check_destination(root)
        data.mkdir(parents=True, exist_ok=True)
        created = []
        try:
            for name in FILES:
                target = data / name
                with target.open("xb") as output:
                    created.append(target)
                    with (staging / name).open("rb") as source:
                        shutil.copyfileobj(source, output)
        except BaseException:
            for target in created:
                target.unlink(missing_ok=True)
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="verify and install an already downloaded release archive")
    args = parser.parse_args()
    try:
        check_destination(ROOT)
        if args.archive:
            install(args.archive, ROOT)
        else:
            print("Downloading the published Django runtime (19 MB)…", flush=True)
            with tempfile.TemporaryDirectory(prefix="repocortex-download-") as temporary:
                archive = Path(temporary) / "runtime.tar.gz"
                with urlopen(URL, timeout=60) as response, archive.open("wb") as target:
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > 25 * 1024 * 1024:
                            raise ValueError("download exceeds the expected archive size")
                        target.write(chunk)
                install(archive, ROOT)
    except (OSError, ValueError, tarfile.TarError) as error:
        print(f"FAIL: {error}")
        return 1
    print("PASS: archive and all five runtime file hashes verified; installed under data/.")
    print("No retraining or database writes. Next: .venv/bin/python scripts/preflight.py")
    print("For a fresh dedicated HydraDB restore, follow docs/recovery.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
