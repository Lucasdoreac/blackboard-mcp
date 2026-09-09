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


# Teto POR FORMATO, não único. 100 MiB foi dimensionado para PDF; texto e
# código não chegam perto disso, e um arquivo de texto gigante é sinal de que
# veio a coisa errada, não de material grande. (Mesma lição da A104 do repo
# SOBER: teto compartilhado assume que o propósito é o mesmo.)
MAX_BYTES_BY_KIND: dict[str, int] = {
    "pdf": MAX_DOWNLOAD_BYTES,
    "office": MAX_DOWNLOAD_BYTES,
    "text": 25 * 1024 * 1024,
}

_HTML_MARKERS = (b"<!doctype html", b"<html", b"<!DOCTYPE HTML")


def verify_signature(path: Path, kind: str) -> None:
    """O byte tem que bater com o FORMATO DECLARADO. Levanta ValueError se não.

    Generaliza a checagem de `%PDF-`, que nunca foi sobre PDF: era sobre o
    conteúdo corresponder ao que o item declarou. Foi ela que impediu uma
    página de LOGIN de ser arquivada como material quando a A88 abriu os links
    mesmo-host — por isso ela é generalizada, jamais removida.

    Para texto não existe magic byte, então a defesa equivalente é dupla:
    decodificar de verdade e NÃO parecer HTML (que é a cara da tal página de
    login). `.html` fica fora do conjunto arquivável justamente porque ali essa
    segunda checagem não teria como existir.
    """
    with path.open("rb") as source:
        head = source.read(1024)
    if kind == "pdf":
        if not head.startswith(b"%PDF-"):
            raise ValueError("Blackboard nao retornou um PDF valido")
        return
    if kind == "office":
        if not head.startswith(b"PK\x03\x04"):
            raise ValueError("Blackboard nao retornou um arquivo Office valido")
        return
    if kind == "text":
        stripped = head.lstrip()[:64].lower()
        if any(stripped.startswith(m.lower()) for m in _HTML_MARKERS):
            raise ValueError("Blackboard retornou HTML (provavel pagina de login), nao o material")
        try:
            head.decode("utf-8")
        except UnicodeDecodeError:
            try:
                head.decode("latin-1")
            except UnicodeDecodeError:
                raise ValueError("Blackboard nao retornou texto decodificavel") from None
        return
    raise ValueError(f"formato declarado desconhecido: {kind!r}")


def persist_download(
    data_home: Path,
    *,
    course_id: str,
    content_id: str,
    title: str,
    suggested_filename: str,
    temporary_path: Path,
    kind: str = "pdf",
) -> dict[str, str | int]:
    """Move a downloaded file into owner-only storage and write a receipt."""
    size = temporary_path.stat().st_size
    teto = MAX_BYTES_BY_KIND.get(kind, MAX_DOWNLOAD_BYTES)
    if size > teto:
        temporary_path.unlink(missing_ok=True)
        raise ValueError(f"material {kind} excede o limite de {teto // 1024 // 1024} MiB")
    if size == 0:
        temporary_path.unlink(missing_ok=True)
        raise ValueError("Blackboard retornou um material vazio")
    try:
        verify_signature(temporary_path, kind)
    except ValueError:
        temporary_path.unlink(missing_ok=True)
        raise

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
        # O FORMATO que `verify_signature` já provou (o magic byte bateu).
        # Sem isto o consumidor (SOBER) re-adivinha o tipo pelo sufixo do
        # TÍTULO — que costuma ser prosa ("Apostila 02 PDM" é um `.pptx`,
        # "Código fonte utilizando Structs" é um `.cpp`) — e roda o extrator
        # errado (real: pypdfium2 num ZIP, "Data format error" em loop).
        "kind": kind,
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


_VERIFY_KINDS = frozenset({"pdf", "text", "office"})


def _sniff_kind(artifact: Path) -> str:
    """Magic-byte format of a file already on disk. Used for receipts written
    before `kind` was recorded — defaulting those to 'pdf' made the consumer
    (SOBER) run pypdfium2 on a `.pptx` ZIP in a loop (real, 2026-09-09,
    "Apostila 02 PDM")."""
    try:
        with artifact.open("rb") as fh:
            head = fh.read(8)
    except OSError:
        return "pdf"
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        return "office"
    return "text"


def _receipt_kind(receipt: dict, artifact: Path | None = None) -> str:
    """The proven format of a receipt. Prefer the recorded `kind`; for an
    older receipt without it, sniff the artifact's magic bytes rather than
    assuming 'pdf'."""
    kind = receipt.get("kind")
    if kind in _VERIFY_KINDS:
        return kind
    if artifact is not None:
        return _sniff_kind(artifact)
    return "pdf"


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
            artifact = receipt_path.parent / str(receipt.get("filename") or "")
            rows.append({
                "course_id": course_id,
                "content_id": content_id,
                "title": str(receipt.get("title") or "Material Blackboard"),
                "kind": _receipt_kind(receipt, artifact),
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
