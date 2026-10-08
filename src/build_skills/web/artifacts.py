"""Content-addressed, immutable delivery archives for concurrent responses."""

import hashlib
import io
import os
import uuid
import zipfile
from pathlib import Path

from build_skills.config import digest
from build_skills.workspace import safe_path


def delivery_archive(job: Path, contents: dict[str, bytes]) -> Path:
    fingerprint = digest(
        {name: hashlib.sha256(data).hexdigest() for name, data in sorted(contents.items())}
    )
    archive = safe_path(job, f"delivery-{fingerprint}.zip")
    if archive.exists():
        try:
            with zipfile.ZipFile(archive) as bundle:
                if sorted(bundle.namelist()) != sorted(contents):
                    raise ValueError("Delivery ZIP inventory was modified")
                for name, data in contents.items():
                    if bundle.getinfo(name).file_size != len(data) or bundle.read(name) != data:
                        raise ValueError("Delivery ZIP contents were modified")
        except (OSError, zipfile.BadZipFile) as exc:
            raise ValueError(
                "Delivery ZIP is corrupt; restore it from validated artifacts"
            ) from exc
        return archive
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, data in sorted(contents.items()):
            safe_path(job, name)
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, data)
    temporary = job / f".archive-{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(buffer.getvalue())
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    return archive
