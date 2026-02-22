"""SessionStore — persist and retrieve FilingSessions from ~/.pfile/sessions/."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pfile.models.session import FilingSession, SessionStatus

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
        """Persist a session to disk, updating updated_at."""
        session.touch()
        self._path(session.id).write_text(
            session.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def load(self, session_id: str) -> FilingSession:
        """Load a session by ID. Raises SessionNotFoundError if not found."""
        path = self._path(session_id)
        if not path.exists():
            raise SessionNotFoundError(f"Session not found: {session_id}")
        return FilingSession.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[FilingSession]:
        """Return all saved sessions, sorted by updated_at descending."""
        sessions = []
        for path in self.base_dir.glob("*.json"):
            try:
                sessions.append(FilingSession.model_validate_json(path.read_text(encoding="utf-8")))
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
