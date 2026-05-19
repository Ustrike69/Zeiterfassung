import gzip
import io
import os
import shutil
import datetime
from pathlib import Path

from db import db_path

BACKUPS_DIR = Path("/opt/zeiterfassung/backups")


def _ensure_dir():
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)


def create_backup_gz(dest_path: str = None):
    """
    Create a gzip-compressed backup of the DB.
    dest_path given → save there, return path string.
    dest_path None  → return (BytesIO, filename).
    """
    src = db_path()
    now = datetime.datetime.now()
    fname = f"zeiterfassung_{now.strftime('%Y-%m-%d_%H-%M')}.db.gz"

    buf = io.BytesIO()
    with open(src, "rb") as f_in:
        with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
            shutil.copyfileobj(f_in, gz)
    buf.seek(0)

    if dest_path:
        _ensure_dir()
        with open(dest_path, "wb") as f_out:
            f_out.write(buf.getvalue())
        return dest_path

    return buf, fname


def list_local_backups():
    """Return list of dicts {name, size, mtime} for each local backup, newest first."""
    _ensure_dir()
    files = []
    for f in sorted(BACKUPS_DIR.glob("*.db.gz"), key=lambda x: x.stat().st_mtime, reverse=True):
        stat = f.stat()
        files.append({
            "name": f.name,
            "size": stat.st_size,
            "mtime": datetime.datetime.fromtimestamp(stat.st_mtime),
        })
    return files


def prune_backups(keep: int = 7):
    """Delete oldest backups, keeping the most recent `keep` files."""
    _ensure_dir()
    files = sorted(BACKUPS_DIR.glob("*.db.gz"), key=lambda x: x.stat().st_mtime, reverse=True)
    for f in files[keep:]:
        try:
            f.unlink()
        except Exception:
            pass


def restore_from_bytes(data: bytes, is_gz: bool) -> str:
    """
    Restore DB from raw bytes. Creates a pre-restore safety backup first.
    Returns the path of the pre-restore backup.
    """
    _ensure_dir()
    now = datetime.datetime.now()
    pre_path = str(BACKUPS_DIR / f"pre_restore_{now.strftime('%Y-%m-%d_%H-%M-%S')}.db.gz")
    create_backup_gz(dest_path=pre_path)

    if is_gz:
        with gzip.open(io.BytesIO(data)) as gz:
            raw = gz.read()
    else:
        raw = data

    src = db_path()
    with open(src, "wb") as f:
        f.write(raw)

    return pre_path
