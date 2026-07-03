"""Exclusive per-process browser profile path abstraction (PSW-S2 / task 2.4).

Provides an :class:`ExclusiveBrowserProfile` value object that guarantees an
exclusive browser profile/user-data directory per persistent worker process,
and enforces the invariant that **destructive cleanup happens only after the
browser has shut down**.

This abstraction is deliberately free of any Playwright dependency. The
concrete ``SessionHandle`` implementation in PSW-S3 will inject the acquired
path into the Chromium launch options; the controller in this slice only needs
the lifecycle contract.

Design decisions (per ``design.md`` Decision 6):

- Path uniqueness is derived from ``pid`` + a random token, so two workers
  (even with reused labels) never share a mutable profile directory.
- ``acquire()`` is **non-destructive**: it only creates the directory and an
  ownership marker. It never deletes existing content.
- ``release_after_shutdown()`` is the only destructive entry point and it is a
  no-op when the profile is not currently in use. ``remove`` cleanup runs
  strictly after ``_in_use`` is cleared.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

_OWNER_MARKER = ".sirhosp-profile-owner"
"""Filename written inside the profile dir to record ownership metadata."""

_DEFAULT_PREFIX = "sirhosp-profile"
"""Prefix for generated profile directory names."""


@dataclass
class ExclusiveBrowserProfile:
    """Exclusive per-process browser profile directory lifecycle.

    Args:
        base_dir: Parent directory for the profile. Defaults to the system
            temp directory when ``None``.
        label: Human-readable worker label included in the dir name for
            operability (e.g. ``"persistent-admissions"``).
        pid: OS process id used for uniqueness. Defaults to the current pid.
        token: Random uniqueness token. Defaults to a freshly generated
            ``uuid4`` hex. Override only for deterministic tests.
    """

    base_dir: Path = field(default_factory=lambda: Path(tempfile.gettempdir()))
    label: str = "persistent-worker"
    pid: int = field(default_factory=os.getpid)
    token: str = field(default_factory=lambda: uuid.uuid4().hex)

    _in_use: bool = field(default=False, init=False, compare=False)

    @property
    def path(self) -> Path:
        """Unique profile directory path for this process instance.

        Two instances — even sharing the same ``label`` and ``pid`` — differ
        by ``token``, guaranteeing exclusivity.
        """
        safe_label = _sanitize(self.label)
        return self.base_dir / f"{_DEFAULT_PREFIX}-{safe_label}-pid{self.pid}-{self.token}"

    @property
    def is_in_use(self) -> bool:
        """Whether this profile has been acquired and not yet released."""
        return self._in_use

    def acquire(self) -> Path:
        """Reserve the profile directory for the current browser session.

        Creates the directory and an ownership marker if missing. This is
        **non-destructive**: pre-existing content inside the directory is
        preserved, and repeated calls are idempotent.

        Returns:
            The acquired profile :class:`Path`.
        """
        if self._in_use:
            return self.path
        self.path.mkdir(parents=True, exist_ok=True)
        (self.path / _OWNER_MARKER).write_text(
            f"pid={self.pid}\nlabel={self.label}\ntoken={self.token}\n",
            encoding="utf-8",
        )
        self._in_use = True
        return self.path

    def release_after_shutdown(self, *, remove: bool = False) -> None:
        """Release the profile after the browser has shut down.

        This is the **only** destructive entry point. It is a no-op when the
        profile is not in use. When ``remove`` is ``True``, the directory is
        deleted **after** marking it as no longer in use, satisfying the
        invariant that destructive cleanup never happens while the browser is
        running.

        Args:
            remove: If ``True``, recursively remove the profile directory.
        """
        if not self._in_use:
            return
        self._in_use = False
        if remove:
            shutil.rmtree(self.path, ignore_errors=True)


def _sanitize(value: str) -> str:
    """Reduce ``value`` to filesystem-safe characters for use in dir names."""
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in value)
    return cleaned.strip("-") or "worker"
