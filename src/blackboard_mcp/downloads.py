"""Safe local storage for Blackboard material downloads.

The browser is the only component that ever sees Blackboard's short-lived
download URL.  Manifests record provenance and integrity, never that URL.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from base64 import b64encode
from datetime import UTC, datetime
from pathlib import Path


MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
MAX_TRANSFER_CHUNK_BYTES = 256 * 1024
_FILENAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")


def _safe_piece(value: str) -> str:
    cleaned = _FILENAME_RE.sub("_", value).strip(" ._")
    return cleaned[:160] or "material"


def download_dir(data_home: Path, course_id: str) -> Path:
    target = data_home / "downloads" / _safe_piece(course_id)
    target.mkdir(parents=True, exist_ok=True)
    target.chmod(0o700)
    return target


def persist_download(
    data_home: Path,
    *,
    course_id: str,
    content_id: str,
    title: str,
    suggested_filename: str,
    temporary_path: Path,
) -> dict[str, str | int]:
    """Move a downloaded file into owner-only storage and write a receipt."""
    size = temporary_path.stat().st_size
    if size > MAX_DOWNLOAD_BYTES:
        temporary_path.unlink(missing_ok=True)
        raise ValueError(f"material excede o limite de {MAX_DOWNLOAD_BYTES // 1024 // 1024} MiB")
    if size == 0:
        temporary_path.unlink(missing_ok=True)
        raise ValueError("Blackboard retornou um material vazio")
    with temporary_path.open("rb") as source:
        if source.read(5) != b"%PDF-":
            temporary_path.unlink(missing_ok=True)
            raise ValueError("Blackboard nao retornou um PDF valido")

    directory = download_dir(data_home, course_id)
    filename = _safe_piece(suggested_filename)
    target = directory / f"{_safe_piece(content_id)}--{filename}"
    os.replace(temporary_path, target)
    target.chmod(0o600)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    receipt = {
        "course_id": course_id,
        "content_id": content_id,
        "title": title,
        "filename": target.name,
        "sha256": digest,
        "size_bytes": size,
        "downloaded_at": datetime.now(UTC).isoformat(),
    }
    receipt_path = target.with_suffix(target.suffix + ".json")
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt_path.chmod(0o600)
    return receipt


def _receipt_path(data_home: Path, course_id: str, content_id: str) -> Path:
    directory = download_dir(data_home, course_id)
    matches = list(directory.glob(f"{_safe_piece(content_id)}--*.json"))
    if len(matches) != 1:
        raise ValueError("material baixado nao encontrado")
    return matches[0]


def verified_receipt(data_home: Path, *, course_id: str, content_id: str) -> dict | None:
    """Return a receipt only when its artifact is present and hash-verified."""
    try:
        receipt_path = _receipt_path(data_home, course_id, content_id)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict) or receipt.get("content_id") != content_id:
            return None
        filename = receipt.get("filename")
        if not isinstance(filename, str) or Path(filename).name != filename:
            return None
        artifact = receipt_path.parent / filename
        if not artifact.is_file():
            return None
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        return receipt if digest == receipt.get("sha256") else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def list_verified_receipts(data_home: Path, *, course_id: str) -> list[dict]:
    """List only intact download receipts, without exposing local paths."""
    directory = download_dir(data_home, course_id)
    rows: list[dict] = []
    for receipt_path in sorted(directory.glob("*.json")):
        try:
            raw = json.loads(receipt_path.read_text(encoding="utf-8"))
            content_id = raw.get("content_id") if isinstance(raw, dict) else None
            if not isinstance(content_id, str):
                continue
            receipt = verified_receipt(data_home, course_id=course_id, content_id=content_id)
            if receipt is None:
                continue
            rows.append({
                "course_id": course_id,
                "content_id": content_id,
                "title": str(receipt.get("title") or "Material Blackboard"),
                "sha256": str(receipt["sha256"]),
                "size_bytes": int(receipt["size_bytes"]),
                "downloaded_at": str(receipt.get("downloaded_at") or ""),
            })
        except (OSError, ValueError, json.JSONDecodeError, KeyError):
            continue
    return rows


def read_download_chunk(
    data_home: Path, *, course_id: str, content_id: str, offset: int, length: int
) -> dict[str, str | int | bool]:
    """Read a bounded block from a verified local artifact for an MCP client."""
    if offset < 0 or length < 1 or length > MAX_TRANSFER_CHUNK_BYTES:
        raise ValueError("intervalo de transferencia invalido")
    receipt_path = _receipt_path(data_home, course_id, content_id)
    receipt: Any = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict) or receipt.get("content_id") != content_id:
        raise ValueError("recibo de material invalido")
    filename = receipt.get("filename")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise ValueError("recibo de material invalido")
    artifact = receipt_path.parent / filename
    if not artifact.is_file():
        raise ValueError("arquivo de material ausente")
    data = artifact.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != receipt.get("sha256"):
        raise ValueError("integridade do material falhou")
    chunk = data[offset : offset + length]
    return {
        "course_id": course_id,
        "content_id": content_id,
        "offset": offset,
        "total_bytes": len(data),
        "sha256": digest,
        "eof": offset + len(chunk) >= len(data),
        "data_b64": b64encode(chunk).decode("ascii"),
    }
