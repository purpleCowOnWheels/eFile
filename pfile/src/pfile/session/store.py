"""SessionStore — persist and retrieve FilingSessions from ~/.pfile/sessions/."""

from __future__ import annotations

import logging
import stat  # used for session file permissions
from pathlib import Path

from pfile.models.session import FilingSession
from pfile.security import decrypt_session, encrypt_session, is_encrypted

log = logging.getLogger(__name__)


_DEFAULT_BASE = Path.home() / ".pfile" / "sessions"


class SessionNotFoundError(Exception):
    pass


class SessionStore:
    def __init__(self, base_dir: Path = _DEFAULT_BASE) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.base_dir / f"{session_id}.json"

    def save(self, session: FilingSession) -> None:
        """Encrypt and persist a session to disk, updating updated_at."""
        session.touch()
        path = self._path(session.id)
        ciphertext = encrypt_session(session.model_dump_json())
        path.write_bytes(ciphertext)
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # owner only

    def load(self, session_id: str) -> FilingSession:
        """Load and decrypt a session by ID. Raises SessionNotFoundError if not found."""
        path = self._path(session_id)
        if not path.exists():
            raise SessionNotFoundError(f"Session not found: {session_id}")
        raw = path.read_bytes()
        if is_encrypted(raw):
            json_str = decrypt_session(raw)
        else:
            # Migrate plaintext legacy sessions transparently
            json_str = raw.decode("utf-8")
            log.info("Migrating plaintext session %s to encrypted format.", session_id)
        session = FilingSession.model_validate_json(json_str)
        if not is_encrypted(raw):
            self.save(session)  # re-save encrypted
        return session

    def list(self) -> list[FilingSession]:
        """Return all saved sessions, sorted by updated_at descending."""
        sessions = []
        for path in self.base_dir.glob("*.json"):
            try:
                raw = path.read_bytes()
                json_str = decrypt_session(raw) if is_encrypted(raw) else raw.decode("utf-8")
                sessions.append(FilingSession.model_validate_json(json_str))
            except Exception as exc:
                log.warning("Skipping unreadable session file %s: %s", path.name, exc)
                continue
        return sorted(sessions, key=lambda s: s.updated_at, reverse=True)

    def delete(self, session_id: str) -> None:
        """Delete a session file. Raises SessionNotFoundError if not found."""
        path = self._path(session_id)
        if not path.exists():
            raise SessionNotFoundError(f"Session not found: {session_id}")
        path.unlink()

    def exists(self, session_id: str) -> bool:
        return self._path(session_id).exists()
