"""Pure DOM policy primitives for legacy session management.

Provides selector constants, countdown parsing, popup detection,
and tab cleanup policies without any Playwright dependency.

Part of PSW-S1 (Persistent Session Worker — Session DOM Policy Primitives).
"""

from __future__ import annotations

import re
from enum import Enum, auto

# ---------------------------------------------------------------------------
# Selector constants
#
# Centralized here so that Playwright-based code imports selectors from
# a single location, avoiding selector drift across modules.
# ---------------------------------------------------------------------------

SEL_SESSION_COUNTER = "#tempoSessao"
"""CSS selector for the legacy session countdown element."""

SEL_RENEWAL_POPUP = "#casca_renovasession"
"""CSS selector for the legacy session renewal popup container."""

SEL_RENEWAL_BUTTON = ".ui-confirmdialog-yes"
"""CSS selector for the semantic 'Renovar' button inside the popup."""

SEL_ROOT_TAB_CLASSES = "tabs-first.tabs-last.tabs-selected"
"""CSS selector fragment identifying the single root/anchor legacy tab."""

SEL_TAB_LAST_CLOSE = "li.tabs-last:not(.tabs-first) a.tabs-close"
"""CSS selector for the close button on the last non-root operational tab."""

# ---------------------------------------------------------------------------
# Session countdown parsing
# ---------------------------------------------------------------------------

# Pattern to extract H, M, S from #tempoSessao with three <span> children.
# Example HTML:
#   <div id="tempoSessao" class="tempo-sessao">
#     Tempo de Sessão: <span>00</span>:<span>29</span>:<span>01</span>
#   </div>
_SESSION_COUNTER_RE = re.compile(
    r'<div[^>]*\bid\s*=\s*["\']tempoSessao["\'][^>]*>.*?'
    r"<span[^>]*>\s*(\d{1,2})\s*</span>\s*:\s*"
    r"<span[^>]*>\s*(\d{2})\s*</span>\s*:\s*"
    r"<span[^>]*>\s*(\d{2})\s*</span>",
    re.DOTALL | re.IGNORECASE,
)


def parse_session_countdown(html: str) -> int | None:
    """Parse remaining seconds from a ``#tempoSessao`` HTML fragment.

    Args:
        html: HTML content that may contain a ``#tempoSessao`` counter
              with three ``<span>`` children for hours, minutes, seconds.

    Returns:
        Total remaining seconds as an ``int``, or ``None`` when the
        counter element is missing, malformed, or unparseable.
    """
    if not html:
        return None
    match = _SESSION_COUNTER_RE.search(html)
    if not match:
        return None
    try:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = int(match.group(3))
    except (ValueError, IndexError):
        return None
    return hours * 3600 + minutes * 60 + seconds


# ---------------------------------------------------------------------------
# Renewal popup detection
# ---------------------------------------------------------------------------

# Pattern to detect visible #casca_renovasession popup.
# The popup is considered visible when aria-hidden="false" AND
# the container's display style is "block" (not "none").
_POPUP_VISIBLE_RE = re.compile(
    r'<div[^>]*\bid\s*=\s*["\']casca_renovasession["\'][^>]*'
    r'aria-hidden\s*=\s*["\']false["\'][^>]*'
    r"display\s*:\s*block",
    re.DOTALL | re.IGNORECASE,
)


def is_renewal_popup_visible(html: str) -> bool:
    """Check whether the legacy session renewal popup is visible.

    The popup is considered visible when ``#casca_renovasession``
    has ``aria-hidden="false"`` **and** ``display: block``.

    Args:
        html: HTML content that may contain the popup container.

    Returns:
        ``True`` if the popup is visible, ``False`` otherwise.
    """
    if not html:
        return False
    return bool(_POPUP_VISIBLE_RE.search(html))


def get_renewal_button_selector() -> str:
    """Return the CSS selector for the semantic renewal button.

    Returns:
        The string ``".ui-confirmdialog-yes"``.
    """
    return SEL_RENEWAL_BUTTON


# ---------------------------------------------------------------------------
# Tab cleanup policy
# ---------------------------------------------------------------------------


class TabCleanupAction(Enum):
    """Action to take for legacy tab cleanup after job completion."""

    PRESERVE_ROOT = auto()
    """Only the root legacy tab exists — no cleanup needed."""

    CLOSE_LAST_NON_ROOT = auto()
    """Close the last non-root operational tab (safe cleanup)."""

    RECOVERY_REQUIRED = auto()
    """Tab state is unsafe, empty, or ambiguous — fall back to recovery."""


class TabCleanupOutcome(Enum):
    """Observable outcome of a legacy DOM-tab cleanup attempt (PSW-S18).

    A PrimeFaces legacy tab is a DOM ``<li>`` element inside ONE Playwright
    Page; it is never a ``BrowserContext.pages`` entry. Cleanup therefore
    clicks the centralized DOM close control on the active page and reports
    exactly one of these observable outcomes. Representation is an enum so
    callers (controller/command) cannot mistake it for a renewal signal.
    """

    ROOT_ONLY = auto()
    """No non-root DOM tab exists; no click occurred."""

    CLOSED_AND_VERIFIED = auto()
    """One non-root tab was closed and the safe state was observed."""

    UNSAFE = auto()
    """Close could not be performed or verified; recovery is required before
    the next claim."""


# Human-readable class strings for tab classification.
# A root-only tab carries all three classes simultaneously.
_CLASS_ROOT_ONLY = "tabs-first tabs-last tabs-selected"
_CLASS_TABS_FIRST = "tabs-first"
_CLASS_TABS_LAST = "tabs-last"


def decide_tab_cleanup(tab_class_list: list[str]) -> TabCleanupAction:
    """Decide tab cleanup action based on current tab class strings.

    Given a list of class attributes for each visible tab ``<li>``
    in the legacy tab bar, this function determines the safe action:

    * Single root tab (``tabs-first tabs-last tabs-selected``) →
      :attr:`TabCleanupAction.PRESERVE_ROOT`.
    * Two or more tabs where the last tab is **not** also the first
      (i.e. it is an operational tab) →
      :attr:`TabCleanupAction.CLOSE_LAST_NON_ROOT`.
    * Empty, missing ``tabs-last`` on the last tab, or ambiguous
      state →
      :attr:`TabCleanupAction.RECOVERY_REQUIRED`.

    Args:
        tab_class_list: A list of strings, where each string is the
            ``class`` attribute of one ``<li>`` tab element, in DOM
            order (first tab to last tab).

    Returns:
        The appropriate :class:`TabCleanupAction`.
    """
    if not tab_class_list:
        return TabCleanupAction.RECOVERY_REQUIRED

    # Single root tab → preserve.
    if len(tab_class_list) == 1:
        root_only = tab_class_list[0].strip() == _CLASS_ROOT_ONLY
        if root_only:
            return TabCleanupAction.PRESERVE_ROOT
        return TabCleanupAction.RECOVERY_REQUIRED

    # Two or more tabs.
    last_classes = tab_class_list[-1]

    # If the last tab is also the first (both classes present on last),
    # the state is unusual — recover.
    if _CLASS_TABS_FIRST in last_classes.split():
        return TabCleanupAction.RECOVERY_REQUIRED

    # The last tab must have 'tabs-last'.
    if _CLASS_TABS_LAST not in last_classes.split():
        return TabCleanupAction.RECOVERY_REQUIRED

    return TabCleanupAction.CLOSE_LAST_NON_ROOT
