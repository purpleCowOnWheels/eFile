"""
Manage raw uploaded PDF files for a session.

Files are saved to  ~/.pfile/uploads/<session_id>/<filer>/<filename>
and tracked in a simple JSON manifest at  ~/.pfile/uploads/<session_id>/manifest.json

The manifest records:
  { "primary": ["w2_2025.pdf", ...], "spouse": ["sp_w2.pdf", ...] }

Parsing happens lazily when the user triggers "Compute", not at upload time.
"""

from __future__ import annotations

import json
from pathlib import Path

_UPLOAD_BASE = Path.home() / ".pfile" / "uploads"


def upload_dir(session_id: str) -> Path:
    d = _UPLOAD_BASE / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def filer_dir(session_id: str, filer: str) -> Path:
    d = upload_dir(session_id) / filer
    d.mkdir(parents=True, exist_ok=True)
    return d


def _manifest_path(session_id: str) -> Path:
    return upload_dir(session_id) / "manifest.json"


def _load_manifest(session_id: str) -> dict[str, list[str]]:
    p = _manifest_path(session_id)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {"primary": [], "spouse": []}


def _save_manifest(session_id: str, manifest: dict[str, list[str]]) -> None:
    _manifest_path(session_id).write_text(json.dumps(manifest, indent=2))


def save_upload(session_id: str, filer: str, filename: str, data: bytes) -> Path:
    """Write an uploaded PDF to disk and register it in the manifest."""
    dest = filer_dir(session_id, filer) / filename
    dest.write_bytes(data)

    manifest = _load_manifest(session_id)
    if filename not in manifest.setdefault(filer, []):
        manifest[filer].append(filename)
    _save_manifest(session_id, manifest)
    return dest


def list_uploads(session_id: str, filer: str) -> list[Path]:
    """Return existing upload paths for a filer (only files that still exist on disk)."""
    manifest = _load_manifest(session_id)
    paths = []
    for name in manifest.get(filer, []):
        p = filer_dir(session_id, filer) / name
        if p.exists():
            paths.append(p)
    return paths


def remove_upload(session_id: str, filer: str, filename: str) -> None:
    """Delete a file and remove it from the manifest."""
    p = filer_dir(session_id, filer) / filename
    if p.exists():
        p.unlink()
    manifest = _load_manifest(session_id)
    manifest.setdefault(filer, [])
    if filename in manifest[filer]:
        manifest[filer].remove(filename)
    _save_manifest(session_id, manifest)


def parse_all(session_id: str, filer: str) -> tuple[list, list[str]]:
    """
    Parse every uploaded PDF for a filer.

    Returns (parsed_docs, error_messages).
    Called from the Compute tab — not from the upload widget.
    """
    from pfile.parsers.dispatcher import UnknownDocumentError, parse

    docs, errors = [], []
    for path in list_uploads(session_id, filer):
        try:
            results = parse(path)
            docs.extend(results)
        except UnknownDocumentError as e:
            errors.append(f"**{path.name}**: {e}")
        except Exception as e:
            errors.append(f"**{path.name}**: parse error — {e}")
    return docs, errors
