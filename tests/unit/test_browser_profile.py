"""Unit tests for exclusive browser profile abstraction (PSW-S2 / task 2.4).

Tests prove:
- exclusivity (two instances never share a path);
- ``acquire()`` is non-destructive and idempotent;
- ``release_after_shutdown`` only removes after releasing (no destructive
  cleanup while in use);
- a real ownership marker is written.
"""

from __future__ import annotations

from pathlib import Path

from apps.ingestion.extractors.browser_profile import (
    _OWNER_MARKER,
    ExclusiveBrowserProfile,
)

# ---------------------------------------------------------------------------
# Exclusivity
# ---------------------------------------------------------------------------


class TestExclusivity:
    def test_two_default_instances_have_different_paths(self, tmp_path: Path) -> None:
        """Two instances with default tokens get distinct paths."""
        a = ExclusiveBrowserProfile(base_dir=tmp_path)
        b = ExclusiveBrowserProfile(base_dir=tmp_path)
        assert a.path != b.path

    def test_same_label_pid_still_unique_by_token(self, tmp_path: Path) -> None:
        """Same label and pid but different token → distinct paths."""
        a = ExclusiveBrowserProfile(
            base_dir=tmp_path, label="w", pid=1, token="t1"
        )
        b = ExclusiveBrowserProfile(
            base_dir=tmp_path, label="w", pid=1, token="t2"
        )
        assert a.path != b.path

    def test_path_contains_label_pid_and_token(self, tmp_path: Path) -> None:
        """Path name embeds label, pid, and token for operability."""
        profile = ExclusiveBrowserProfile(
            base_dir=tmp_path, label="admissions", pid=4242, token="deadbeef"
        )
        name = profile.path.name
        assert "admissions" in name
        assert "pid4242" in name
        assert "deadbeef" in name

    def test_unsafe_label_chars_are_sanitized(self, tmp_path: Path) -> None:
        """Unsafe label characters are replaced, never empty."""
        profile = ExclusiveBrowserProfile(
            base_dir=tmp_path, label="../evil name!!", pid=1, token="t"
        )
        name = profile.path.name
        assert ".." not in name
        assert " " not in name


# ---------------------------------------------------------------------------
# acquire — non-destructive + idempotent
# ---------------------------------------------------------------------------


class TestAcquire:
    def test_acquire_creates_directory(self, tmp_path: Path) -> None:
        profile = ExclusiveBrowserProfile(base_dir=tmp_path)
        path = profile.acquire()
        assert path.is_dir()
        assert profile.is_in_use is True

    def test_acquire_writes_ownership_marker(self, tmp_path: Path) -> None:
        profile = ExclusiveBrowserProfile(
            base_dir=tmp_path, label="x", pid=99, token="tok"
        )
        path = profile.acquire()
        marker = path / _OWNER_MARKER
        assert marker.is_file()
        content = marker.read_text(encoding="utf-8")
        assert "pid=99" in content
        assert "label=x" in content
        assert "token=tok" in content

    def test_acquire_is_idempotent(self, tmp_path: Path) -> None:
        """Repeated acquire keeps the same path and stays in use."""
        profile = ExclusiveBrowserProfile(base_dir=tmp_path)
        first = profile.acquire()
        second = profile.acquire()
        assert first == second
        assert profile.is_in_use is True

    def test_acquire_preserves_existing_content(self, tmp_path: Path) -> None:
        """Acquire never deletes existing content (non-destructive)."""
        profile = ExclusiveBrowserProfile(base_dir=tmp_path)
        path = profile.acquire()
        seed = path / "Default" / "Cookies"
        seed.parent.mkdir(parents=True, exist_ok=True)
        seed.write_text("pretend-cache", encoding="utf-8")

        # Acquire again (idempotent) — content must survive.
        profile.acquire()
        assert seed.read_text(encoding="utf-8") == "pretend-cache"


# ---------------------------------------------------------------------------
# release_after_shutdown — invariant: no destructive cleanup while in use
# ---------------------------------------------------------------------------


class TestReleaseAfterShutdown:
    def test_release_is_noop_when_not_in_use(self, tmp_path: Path) -> None:
        profile = ExclusiveBrowserProfile(base_dir=tmp_path)
        # Never acquired → release must do nothing and not raise.
        profile.release_after_shutdown(remove=True)
        assert profile.is_in_use is False

    def test_release_without_remove_keeps_directory(self, tmp_path: Path) -> None:
        profile = ExclusiveBrowserProfile(base_dir=tmp_path)
        path = profile.acquire()
        profile.release_after_shutdown(remove=False)
        assert profile.is_in_use is False
        assert path.is_dir()

    def test_release_with_remove_deletes_directory(self, tmp_path: Path) -> None:
        profile = ExclusiveBrowserProfile(base_dir=tmp_path)
        path = profile.acquire()
        profile.release_after_shutdown(remove=True)
        assert profile.is_in_use is False
        assert not path.exists()

    def test_no_destructive_method_runs_while_in_use(self, tmp_path: Path) -> None:
        """The only destructive path (remove) is gated behind release.

        There is no public API to delete the profile while ``is_in_use`` is
        True: ``release_after_shutdown`` clears ``_in_use`` before any rmtree,
        and ``acquire`` is non-destructive. This test documents the invariant
        by exercising acquire -> acquire -> release(remove=True) and asserting
        the directory only disappears after release.
        """
        profile = ExclusiveBrowserProfile(base_dir=tmp_path)
        path = profile.acquire()
        profile.acquire()  # idempotent, still in use
        assert profile.is_in_use is True
        assert path.exists()  # still present while in use
        profile.release_after_shutdown(remove=True)
        assert not path.exists()


# ---------------------------------------------------------------------------
# Two workers side-by-side (production-worker-runtime-io-control scenario)
# ---------------------------------------------------------------------------


class TestSideBySideWorkers:
    def test_two_workers_acquire_distinct_profiles_concurrently(
        self, tmp_path: Path
    ) -> None:
        """Two persistent workers get isolated, non-overlapping profiles."""
        w1 = ExclusiveBrowserProfile(base_dir=tmp_path, label="persistent-A")
        w2 = ExclusiveBrowserProfile(base_dir=tmp_path, label="persistent-B")
        p1 = w1.acquire()
        p2 = w2.acquire()
        # Distinct sibling directories under the same base.
        assert p1 != p2
        assert p1.parent == p2.parent == tmp_path
        # Both independent: releasing one never affects the other.
        w1.release_after_shutdown(remove=True)
        assert not p1.exists()
        assert p2.is_dir()
