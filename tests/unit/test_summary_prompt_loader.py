"""Tests for summary prompt loader (STP-S2 RED phase).

TDD: tests first (RED), then implement (GREEN), then refactor.

Covers:
    - Loading phase 1 canonical prompt from versioned file.
    - Loading phase 2 default render prompt from versioned file.
    - Explicit error when required file is missing.
"""

from __future__ import annotations

import pytest

from apps.summaries.prompt_loader import (
    PromptFileNotFoundError,
    load_phase1_prompt,
    load_phase2_prompt,
)


class TestLoadPhase1Prompt:
    """Tests for loading the phase 1 canonical prompt."""

    def test_loads_content_from_file(self, tmp_path):
        """Phase 1 prompt is loaded from a versioned file."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "phase1_canonical_v1.md"
        expected_content = (
            "# Phase 1 Canonical Prompt\n\n"
            "You are a clinical assistant responsible for maintaining "
            "a progressive hospital admission summary."
        )
        prompt_file.write_text(expected_content, encoding="utf-8")

        content = load_phase1_prompt(prompts_dir=prompts_dir)

        assert "clinical assistant" in content
        assert "progressive hospital admission summary" in content
        assert expected_content == content

    def test_raises_when_file_missing(self, tmp_path):
        """Explicit error when the phase 1 prompt file does not exist."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()

        with pytest.raises(PromptFileNotFoundError) as exc_info:
            load_phase1_prompt(prompts_dir=prompts_dir)

        error_message = str(exc_info.value)
        assert "phase1_canonical_v1.md" in error_message
        assert str(prompts_dir) in error_message

    def test_raises_when_directory_missing(self, tmp_path):
        """Explicit error when the prompts directory itself is missing."""
        prompts_dir = tmp_path / "nonexistent"

        with pytest.raises(PromptFileNotFoundError) as exc_info:
            load_phase1_prompt(prompts_dir=prompts_dir)

        error_message = str(exc_info.value)
        assert "phase1_canonical_v1.md" in error_message


class TestLoadPhase2Prompt:
    """Tests for loading the phase 2 default render prompt."""

    def test_loads_content_from_file(self, tmp_path):
        """Phase 2 prompt is loaded from a versioned file."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        prompt_file = prompts_dir / "phase2_default_v1.md"
        expected_content = (
            "# Phase 2 Default Render Prompt\n\n"
            "Based on the clinical summary above, render a clean "
            "markdown document for the end user."
        )
        prompt_file.write_text(expected_content, encoding="utf-8")

        content = load_phase2_prompt(prompts_dir=prompts_dir)

        assert "Render Prompt" in content
        assert "end user" in content
        assert expected_content == content

    def test_raises_when_file_missing(self, tmp_path):
        """Explicit error when the phase 2 prompt file does not exist."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()

        with pytest.raises(PromptFileNotFoundError) as exc_info:
            load_phase2_prompt(prompts_dir=prompts_dir)

        error_message = str(exc_info.value)
        assert "phase2_default_v1.md" in error_message
        assert str(prompts_dir) in error_message


class TestLoadPromptFileIndependence:
    """Phase 1 and phase 2 prompts are independent files."""

    def test_only_phase1_exists(self, tmp_path):
        """When only phase1 file exists, phase1 loads but phase2 fails."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "phase1_canonical_v1.md").write_text("phase1 content")

        phase1 = load_phase1_prompt(prompts_dir=prompts_dir)
        assert phase1 == "phase1 content"

        with pytest.raises(PromptFileNotFoundError):
            load_phase2_prompt(prompts_dir=prompts_dir)

    def test_only_phase2_exists(self, tmp_path):
        """When only phase2 file exists, phase2 loads but phase1 fails."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "phase2_default_v1.md").write_text("phase2 content")

        phase2 = load_phase2_prompt(prompts_dir=prompts_dir)
        assert phase2 == "phase2 content"

        with pytest.raises(PromptFileNotFoundError):
            load_phase1_prompt(prompts_dir=prompts_dir)
