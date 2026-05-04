"""Load versioned prompt files from the repository (STP-S2).

Provides typed loaders for standard prompts used in the two-phase
summary pipeline.  Prompts are stored as Markdown files in the
``prompts/`` subdirectory adjacent to this module, enabling
Git-based review and version history.

Exports:
    load_phase1_prompt: load the phase 1 canonical clinical prompt.
    load_phase2_prompt: load the phase 2 default render prompt.
    PromptFileNotFoundError: raised when a required file is absent.
"""

from __future__ import annotations

from pathlib import Path


class PromptFileNotFoundError(FileNotFoundError):
    """Raised when a required prompt file is missing from the repository.

    The message includes the full path so that the operator knows
    exactly which file is expected and where it should reside.
    """


def _resolve_prompts_dir(prompts_dir: Path | None = None) -> Path:
    """Resolve the prompts directory.

    When no explicit directory is given, defaults to the ``prompts/``
    subdirectory adjacent to this module.
    """
    if prompts_dir is not None:
        return Path(prompts_dir)
    return Path(__file__).resolve().parent / "prompts"


def _load_prompt_file(filename: str, prompts_dir: Path | None = None) -> str:
    """Load a prompt file from the prompts directory.

    Args:
        filename: Name of the prompt file (e.g. ``phase1_canonical_v1.md``).
        prompts_dir: Optional explicit path to the prompts directory.
            When ``None``, defaults to the directory adjacent to this module.

    Returns:
        File contents as a UTF-8 string (with trailing whitespace stripped).

    Raises:
        PromptFileNotFoundError: If the file does not exist.
    """
    directory = _resolve_prompts_dir(prompts_dir)
    filepath = directory / filename

    if not filepath.is_file():
        raise PromptFileNotFoundError(
            f"Required prompt file not found: {filepath}. "
            f"Ensure the file is versioned in the repository: "
            f"{directory}/{filename}"
        )

    return filepath.read_text(encoding="utf-8").strip()


def load_phase1_prompt(prompts_dir: Path | None = None) -> str:
    """Load the phase 1 canonical clinical prompt.

    This prompt defines the structured clinical summary contract
    (structured state + Markdown narrative + evidence references).
    It is loaded from ``phase1_canonical_v1.md``.

    Args:
        prompts_dir: Optional explicit path to the prompts directory
            (useful for testing with temporary directories).

    Returns:
        Prompt content as a string.

    Raises:
        PromptFileNotFoundError: If ``phase1_canonical_v1.md`` is missing
            from the prompts directory.
    """
    return _load_prompt_file("phase1_canonical_v1.md", prompts_dir)


def load_phase2_prompt(prompts_dir: Path | None = None) -> str:
    """Load the phase 2 default render prompt.

    This prompt instructs the LLM to render the canonical clinical
    summary into a clean, readable Markdown output.  It is loaded
    from ``phase2_default_v1.md``.

    Args:
        prompts_dir: Optional explicit path to the prompts directory
            (useful for testing with temporary directories).

    Returns:
        Prompt content as a string.

    Raises:
        PromptFileNotFoundError: If ``phase2_default_v1.md`` is missing
            from the prompts directory.
    """
    return _load_prompt_file("phase2_default_v1.md", prompts_dir)
