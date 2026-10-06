"""Repeatable headless browser journeys for one dev verification session.

The driver is split in three pieces so the runner can be tested without a
browser:

* ``RequestPolicy`` decides, per request, whether the browser may leave the
  portal: origin, method and path are checked for the main document, static
  assets, redirects and popups alike.
* ``Observations`` collects console errors, unexpected HTTP statuses, missing
  required assets, refused requests and policy blocks, always sanitized.
* ``SmokeDriver`` orchestrates isolated contexts per role and viewport,
  records evidence, and never reports PASS for a missing prerequisite.

Only the owned session credentials cross into the driver, they stay in
memory, and no artifact written here contains a password, cookie or header.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, quote, urlsplit

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
SKIPPED = "SKIPPED"

EXIT_CODES = {PASS: 0, FAIL: 1, BLOCKED: 2, SKIPPED: 3}

# No operational origin lives in this module: every journey receives the
# validated canonical origin explicitly (ORIG-001). Native tests pass http
# loopback or .invalid origins; the private profile never allows http.
EVIDENCE_ROOT = Path("/tmp/sirhosp-verification")

# An allowed origin is scheme + host + effective port: the explicit port, or the
# scheme default when the URL omits it. ``:443`` and a bare host are the same
# origin; any other port is a different origin and stays outside the allowlist.
DEFAULT_PORTS: Mapping[str, int] = {"https": 443, "http": 80}

FEATURES = ("auth", "smoke")
ROLE_NAMES = ("user", "admin")
OWNED_USERNAMES = {"user": "verify_user", "admin": "verify_admin"}

REDACTED = "«redacted»"
# Marker written into the artifacts when a run secret reached the evidence text;
# the run is downgraded to FAIL whenever it appears.
SANITIZATION_MARKER = "SANITIZATION FAILED"
SANITIZATION_KEY = "sanitization"
# Console prefix used by the popup guard installed in every owned context.
POPUP_BLOCK_MARKER = "SIRHOSP-POPUP-BLOCKED"
ARTIFACT_NAMES = ("report.json", "summary.md")

# Installed as a context init script: an unforeseen popup must be stopped at
# its source, before its first request leaves the owned context.
POPUP_GUARD_SCRIPT = (
    "(() => {\n"
    "  const report = (kind, url) => {\n"
    f"    console.error('{POPUP_BLOCK_MARKER} ' + kind + ' ' + String(url || ''));\n"
    "  };\n"
    "  const closest = (node, selector) =>\n"
    "    (node && node.closest ? node.closest(selector) : null);\n"
    "  window.open = (url) => { report('open', url); return null; };\n"
    "  document.addEventListener('click', (event) => {\n"
    "    const anchor = closest(event.target, 'a[target=_blank]');\n"
    "    if (anchor) { event.preventDefault(); report('anchor', anchor.href); return; }\n"
    "    const form = closest(event.target, 'form[target=_blank]');\n"
    "    if (form) { event.preventDefault(); report('form', form.action); }\n"
    "  }, true);\n"
    "  document.addEventListener('submit', (event) => {\n"
    "    const form = closest(event.target, 'form[target=_blank]');\n"
    "    if (form) { event.preventDefault(); report('form', form.action); }\n"
    "  }, true);\n"
    "})();\n"
)

HTMX_BADGE_PATH = "/atualizacao-censo/"
POLL_COUNT = 2
POLL_TIMEOUT_MS = 90000

# Shell reads the driver is allowed to perform. Everything else on the portal
# host is refused, including GETs that enqueue jobs or export data.
SHELL_PATHS = frozenset(
    {
        "/",
        "/login/",
        "/logout/",
        "/painel/",
        "/censo/",
        "/perfil/",
        "/atualizacao-censo/",
    }
)
POST_PATHS = frozenset({"/login/", "/logout/"})
BUSINESS_MUTATION_PATHS = frozenset(
    {
        "/ingestao/criar/",
        "/ingestao/sincronizar-internacoes/",
        "/ingestao/sincronizar-demograficos/",
        "/censo/exportar/",
        "/statistics/export/",
        "/reconciliacao/exportar/",
    }
)
STATIC_PREFIX = "/static/"
IGNORED_PATHS = frozenset({"/favicon.ico"})

# Edge-injected telemetry is refused like anything else, but it is classified
# separately: it is not product behavior and must not fail an otherwise clean
# run. Blocking the beacon also prevents the Cloudflare RUM POST.
EDGE_HOSTS = frozenset({"static.cloudflareinsights.com"})
EDGE_PATH_PREFIX = "/cdn-cgi/"

# Versioned asset paths only. Hosts are never opened as a whole.
CDN_PATHS: Mapping[str, frozenset[str]] = {
    "cdn.jsdelivr.net": frozenset(
        {
            "/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css",
            "/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js",
            "/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css",
            "/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff",
            "/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff2",
            "/npm/tom-select@2.3.1/dist/css/tom-select.bootstrap5.min.css",
            "/npm/tom-select@2.3.1/dist/js/tom-select.complete.min.js",
        }
    ),
    "unpkg.com": frozenset(
        {
            "/htmx.org@2.0.4",
            "/htmx.org@2.0.4/dist/htmx.min.js",
        }
    ),
}

REQUIRED_ASSETS = (
    "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css",
    "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css",
    "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js",
    "https://unpkg.com/htmx.org@2.0.4",
)
CENSUS_REQUIRED_ASSETS = (
    "https://cdn.jsdelivr.net/npm/tom-select@2.3.1/dist/css/tom-select.bootstrap5.min.css",
    "https://cdn.jsdelivr.net/npm/tom-select@2.3.1/dist/js/tom-select.complete.min.js",
)
CENSUS_CASE_IDS = frozenset({"census-tomselect", "census-filter-positive"})

QUERY_KEYS = ("q", "unidade", "especialidade", "finding", "ordenar")


class DriverTimeout(Exception):
    """A browser interaction exceeded the driver timeout."""


class DriverBlocked(Exception):
    """A required prerequisite is missing; the case is BLOCKED, never PASS."""


# ---------------------------------------------------------------------------
# Viewports
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Viewport:
    name: str
    width: int
    height: int


DESKTOP = Viewport(name="desktop", width=1440, height=900)
MOBILE = Viewport(name="mobile", width=390, height=844)
VIEWPORTS: Mapping[str, Viewport] = {DESKTOP.name: DESKTOP, MOBILE.name: MOBILE}


# ---------------------------------------------------------------------------
# Request policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    category: str
    reason: str


def sanitize_url(url: str) -> str:
    """Drop query and fragment: auth payloads never reach the evidence."""
    parts = urlsplit(url)
    if not parts.scheme and not parts.netloc:
        return parts.path or url
    return f"{parts.scheme}://{parts.netloc}{parts.path or '/'}"


def effective_port(parts: SplitResult) -> int | None:
    """Explicit port, or the scheme default when the URL omits it."""
    if parts.port is not None:
        return parts.port
    return DEFAULT_PORTS.get(parts.scheme)


@dataclass(frozen=True)
class RequestPolicy:
    origin: str

    def decide(self, url: str, method: str) -> PolicyDecision:
        parts = urlsplit(url)
        upper = method.upper()
        host = (parts.hostname or "").lower()
        path = parts.path or "/"
        if host in EDGE_HOSTS or path.startswith(EDGE_PATH_PREFIX):
            return PolicyDecision(False, "edge", "edge-injected telemetry refused")
        if parts.scheme in {"data", "blob"}:
            return PolicyDecision(True, "allowed", "inline asset")
        # The authorized origin also fixes the scheme: the canonical
        # verification origin uses https, while native tests drive http
        # loopback or .invalid origins passed explicitly to the policy.
        origin = urlsplit(self.origin)
        if parts.scheme not in DEFAULT_PORTS or parts.scheme != origin.scheme:
            return PolicyDecision(False, "policy", "scheme outside the authorized origin")
        port = effective_port(parts)
        if host == (origin.hostname or "").lower():
            if port != effective_port(origin):
                return PolicyDecision(False, "policy", "port outside the authorized origin")
            return self._decide_portal(upper, path)
        return self._decide_cdn(upper, host, port, path)

    def _decide_portal(self, method: str, path: str) -> PolicyDecision:
        if path in IGNORED_PATHS:
            return PolicyDecision(True, "ignored", "browser default asset")
        if path.startswith(STATIC_PREFIX):
            if method == "GET":
                return PolicyDecision(True, "allowed", "static asset")
            return PolicyDecision(False, "policy", "static asset is read-only")
        if path in BUSINESS_MUTATION_PATHS:
            return PolicyDecision(False, "policy", "business mutation route refused")
        if path in SHELL_PATHS:
            if method == "GET":
                return PolicyDecision(True, "allowed", "shell read route")
            if method == "POST" and path in POST_PATHS:
                return PolicyDecision(True, "allowed", "authentication route")
            return PolicyDecision(False, "policy", "method refused on this route")
        return PolicyDecision(False, "policy", "path outside the allowlist")

    def _decide_cdn(self, method: str, host: str, port: int | None, path: str) -> PolicyDecision:
        allowed_paths = CDN_PATHS.get(host)
        if allowed_paths is None:
            return PolicyDecision(False, "policy", "host outside the allowlist")
        if port != DEFAULT_PORTS["https"]:
            return PolicyDecision(False, "policy", "port outside the allowlist")
        if method != "GET":
            return PolicyDecision(False, "policy", "cdn assets are read-only")
        if path not in allowed_paths:
            return PolicyDecision(False, "policy", "cdn path outside the allowlist")
        return PolicyDecision(True, "allowed", "versioned cdn asset")


def _is_asset(url: str) -> bool:
    parts = urlsplit(url)
    if (parts.hostname or "").lower() in CDN_PATHS:
        return True
    return (parts.path or "/").startswith(STATIC_PREFIX)


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------


class Observations:
    """Per-context record of everything the browser observed and attempted."""

    def __init__(
        self,
        policy: RequestPolicy,
        *,
        expect_blocks: bool = False,
        redactions: Sequence[str] = (),
    ) -> None:
        self.policy = policy
        self.expect_blocks = expect_blocks
        self._redactions = tuple(secret for secret in redactions if secret)
        self.violations: list[str] = []
        self.expected_blocks: list[str] = []
        self.edge_blocks: list[str] = []
        self.popup_blocks: list[str] = []
        self.websocket_blocks: list[str] = []
        self.js_errors: list[str] = []
        self.http_unexpected: list[str] = []
        self.failed_requests: list[str] = []
        self.observed_assets: set[str] = set()
        self._suppressed: set[str] = set()
        # A failed CDP interception cannot be trusted: a paused request could
        # not be continued or failed, so the hop layer is compromised and the
        # remaining journeys must not run. The driver checks this flag to abort
        # the remaining cases and groups, so the owned browser is closed by the
        # surrounding finally immediately after this group. It is signalled
        # before any release attempt because a release may suspend; and a failed
        # release cannot be retried: in Playwright 1.58 BrowserContext.close()
        # flags the context closed before the effective dispose.
        self.fatal: bool = False

    def redact(self, text: str) -> str:
        for secret in self._redactions:
            text = text.replace(secret, REDACTED)
        return text

    def decide(self, url: str, method: str) -> PolicyDecision:
        decision = self.policy.decide(url, method)
        if decision.allowed:
            return decision
        clean = sanitize_url(url)
        entry = f"{method.upper()} {clean} — {decision.reason}"
        self._suppressed.add(clean)
        if decision.category == "edge":
            self.edge_blocks.append(entry)
        elif self.expect_blocks:
            self.expected_blocks.append(entry)
        else:
            self.violations.append(entry)
        return decision

    def note_console(self, level: str, text: str) -> None:
        message = str(text or "")
        if message.startswith(POPUP_BLOCK_MARKER):
            self.note_popup_attempt(message[len(POPUP_BLOCK_MARKER) :].strip())
            return
        if level != "error":
            return
        if message.startswith("Failed to load resource"):
            # The browser omits the URL here; missing assets and unexpected
            # statuses are proven through responses instead.
            return
        self.js_errors.append(self.redact(message))

    def note_popup_attempt(self, detail: str) -> None:
        """The popup guard refused an attempt before its first request."""
        kind, _, url = detail.partition(" ")
        self.popup_blocks.append(
            f"popup {kind or 'open'} refused before its first request: {sanitize_url(url.strip())}"
        )

    def note_popup_page(self, url: str) -> None:
        """A page the driver did not create appeared inside an owned context."""
        self.popup_blocks.append(
            f"unforeseen popup page opened in an owned context: {sanitize_url(url)}"
        )

    def note_websocket_attempt(self, url: str) -> None:
        """The passive websocket handler never connects: the handshake stops here."""
        self.websocket_blocks.append(
            f"websocket refused before the handshake: {sanitize_url(url)}"
        )

    def note_page_error(self, text: str) -> None:
        self.js_errors.append(self.redact(str(text)))

    def note_response(self, url: str, status: int) -> None:
        parts = urlsplit(url)
        path = parts.path or "/"
        if status == 200 and _is_asset(url):
            self.observed_assets.add(sanitize_url(url))
        if status >= 400 and path not in IGNORED_PATHS:
            self.http_unexpected.append(f"{sanitize_url(url)} -> {status}")

    def note_request_failed(self, url: str, failure: str) -> None:
        clean = sanitize_url(url)
        if clean in self._suppressed:
            return
        self.failed_requests.append(f"{clean} {failure}".strip())

    def missing_assets(self, required: Sequence[str]) -> list[str]:
        missing = []
        for asset in required:
            if not any(
                entry == asset or entry.startswith(asset + "/") for entry in self.observed_assets
            ):
                missing.append(asset)
        return missing


def compare_queue_metadata(
    before: Mapping[str, int], after: Mapping[str, int]
) -> tuple[bool, list[str]]:
    """Compare queue counters; any drift is a business effect, never deleted."""
    changes = []
    for key in sorted(set(before) | set(after)):
        old = _as_count(before.get(key))
        new = _as_count(after.get(key))
        if old != new:
            changes.append(f"{key} {old} -> {new}")
    return (not changes, changes)


def _as_count(value: object) -> int:
    if type(value) is int:
        return value
    return 0


# ---------------------------------------------------------------------------
# Results and evidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CaseResult:
    case: str
    role: str
    viewport: str
    status: str
    detail: str = ""
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaseOutcome:
    status: str
    detail: str = ""
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class Aggregate:
    status: str
    exit_code: int
    counts: dict[str, int]
    cases: tuple[CaseResult, ...]
    reasons: tuple[str, ...]


@dataclass
class RunEvidence:
    run_id: str
    feature: str
    target: str
    roles: tuple[str, ...]
    viewports: tuple[str, ...]
    started_at: str
    finished_at: str = ""
    cases: list[CaseResult] = field(default_factory=list)
    request_violations: list[str] = field(default_factory=list)
    deliberate_blocks: list[str] = field(default_factory=list)
    edge_blocks: list[str] = field(default_factory=list)
    js_errors: list[str] = field(default_factory=list)
    http_unexpected: list[str] = field(default_factory=list)
    failed_requests: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    missing_assets: list[str] = field(default_factory=list)
    queue_changes: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    cleanup: str = "UNKNOWN"
    failure: str = ""
    # Sanitization hygiene of the run artifacts (PASS/FAIL) and the reasons it
    # did not pass; a FAIL downgrades the whole run.
    hygiene: str = "UNKNOWN"
    sanitization_failures: list[str] = field(default_factory=list)
    # In-memory run secrets used to scrub the artifacts. Never serialized.
    secrets: tuple[str, ...] = ()


def build_aggregate(evidence: RunEvidence) -> Aggregate:
    counts = {PASS: 0, FAIL: 0, BLOCKED: 0, SKIPPED: 0}
    for case in evidence.cases:
        counts[case.status] = counts.get(case.status, 0) + 1
    reasons: list[str] = []
    if evidence.failure:
        reasons.append(f"run failure: {evidence.failure}")
    if evidence.cleanup != PASS:
        reasons.append(f"cleanup {evidence.cleanup}")
    if evidence.hygiene == FAIL:
        reasons.append(f"{SANITIZATION_MARKER}: run secrets reached the evidence text")
        reasons.extend(evidence.sanitization_failures)
    reasons.extend(evidence.request_violations)
    reasons.extend(evidence.js_errors)
    reasons.extend(evidence.http_unexpected)
    reasons.extend(evidence.failed_requests)
    reasons.extend(evidence.missing_assets)
    reasons.extend(evidence.queue_changes)
    for case in evidence.cases:
        if case.status == FAIL:
            reasons.append(f"{case.case} ({case.role}/{case.viewport}): {case.detail}")
    statuses = [case.status for case in evidence.cases]
    if reasons:
        status = FAIL
    elif not statuses:
        status = BLOCKED
        reasons.append("no case was executed")
    elif FAIL in statuses:
        status = FAIL
    elif BLOCKED in statuses:
        status = BLOCKED
    elif SKIPPED in statuses:
        status = SKIPPED
    else:
        status = PASS
    return Aggregate(
        status=status,
        exit_code=EXIT_CODES[status],
        counts=counts,
        cases=tuple(evidence.cases),
        reasons=tuple(reasons),
    )


def _summary_markdown(evidence: RunEvidence, aggregate: Aggregate) -> str:
    lines = [
        f"# Verification run `{evidence.run_id}`",
        "",
        f"- feature: `{evidence.feature}`",
        f"- target: `{evidence.target}`",
        f"- status: **{aggregate.status}** (exit {aggregate.exit_code})",
        f"- cleanup: `{evidence.cleanup}`",
        f"- started: {evidence.started_at}",
        f"- finished: {evidence.finished_at}",
        f"- roles: {', '.join(evidence.roles)}",
        f"- viewports: {', '.join(evidence.viewports)}",
        "",
        "## Cases",
        "",
        "| case | role | viewport | status | detail |",
        "| --- | --- | --- | --- | --- |",
    ]
    for case in evidence.cases:
        detail = case.detail.replace("|", "/")
        lines.append(f"| {case.case} | {case.role} | {case.viewport} | {case.status} | {detail} |")
    sections = (
        ("Run failure", [evidence.failure] if evidence.failure else []),
        ("Sanitization", [evidence.hygiene, *evidence.sanitization_failures]),
        ("Policy violations", evidence.request_violations),
        ("Deliberate blocks", evidence.deliberate_blocks),
        ("Edge telemetry refused", evidence.edge_blocks),
        ("JavaScript errors", evidence.js_errors),
        ("Unexpected HTTP", evidence.http_unexpected),
        ("Failed requests", evidence.failed_requests),
        ("Missing required assets", evidence.missing_assets),
        ("Queue metadata changes", evidence.queue_changes),
        ("Reasons", list(aggregate.reasons)),
        ("Screenshots", evidence.screenshots),
    )
    for title, entries in sections:
        lines.extend(["", f"## {title}", ""])
        if entries:
            lines.extend(f"- {entry}" for entry in entries)
        else:
            lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def _report_payload(evidence: RunEvidence, aggregate: Aggregate) -> dict[str, Any]:
    return {
        "run_id": evidence.run_id,
        "feature": evidence.feature,
        "target": evidence.target,
        "roles": list(evidence.roles),
        "viewports": list(evidence.viewports),
        "started_at": evidence.started_at,
        "finished_at": evidence.finished_at,
        "status": aggregate.status,
        "exit_code": aggregate.exit_code,
        "cleanup": evidence.cleanup,
        "failure": evidence.failure,
        SANITIZATION_KEY: evidence.hygiene,
        "sanitization_failures": list(evidence.sanitization_failures),
        "reasons": list(aggregate.reasons),
        "counts": aggregate.counts,
        "cases": [
            {
                "case": case.case,
                "role": case.role,
                "viewport": case.viewport,
                "status": case.status,
                "detail": case.detail,
                "evidence": list(case.evidence),
            }
            for case in evidence.cases
        ],
        "request_violations": list(evidence.request_violations),
        "deliberate_blocks": list(evidence.deliberate_blocks),
        "edge_blocks": list(evidence.edge_blocks),
        "js_errors": list(evidence.js_errors),
        "http_unexpected": list(evidence.http_unexpected),
        "failed_requests": list(evidence.failed_requests),
        "assets": sorted(evidence.assets),
        "missing_assets": list(evidence.missing_assets),
        "queue_changes": list(evidence.queue_changes),
        "screenshots": list(evidence.screenshots),
    }


def _render_artifacts(evidence: RunEvidence) -> dict[str, str]:
    """Serialize both artifacts in memory; nothing is written from here."""
    aggregate = build_aggregate(evidence)
    return {
        "report.json": json.dumps(
            _report_payload(evidence, aggregate), indent=2, ensure_ascii=False
        )
        + "\n",
        "summary.md": _summary_markdown(evidence, aggregate),
    }


def secret_variants(secrets: Sequence[str]) -> tuple[str, ...]:
    """Run secrets plus the percent-encoded form a URL or header would carry."""
    variants: list[str] = []
    for secret in secrets:
        for candidate in (str(secret), quote(str(secret), safe="")):
            if candidate and candidate not in variants:
                variants.append(candidate)
    return tuple(variants)


def contains_secret(text: str | bytes, secrets: Sequence[str]) -> bool:
    blob = text.decode("utf-8", "replace") if isinstance(text, bytes) else str(text)
    return any(secret in blob for secret in secrets)


def scrub_text(text: str, secrets: Sequence[str], marker: str = REDACTED) -> str:
    for secret in secrets:
        text = text.replace(secret, marker)
    return text


def scrub_object(value: Any, secrets: Sequence[str]) -> Any:
    """A copy of a JSON-like value with every secret replaced in memory."""
    if isinstance(value, str):
        return scrub_text(value, secrets)
    if isinstance(value, Mapping):
        return {
            scrub_text(str(key), secrets): scrub_object(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [scrub_object(item, secrets) for item in value]
    return value


def sanitize_json_payload(payload: Mapping[str, Any], secrets: Sequence[str]) -> tuple[str, bool]:
    """Serialize a CLI payload in memory and verify it before it is printed.

    The returned text never carries a run secret; ``clean`` is False when a
    secret had to be redacted on the way out.
    """
    variants = secret_variants(secrets)
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    if not variants or not contains_secret(text, variants):
        return text, True
    safe = scrub_object(dict(payload), variants)
    safe[SANITIZATION_KEY] = SANITIZATION_MARKER
    redacted = json.dumps(safe, separators=(",", ":"), ensure_ascii=False)
    if contains_secret(redacted, variants):
        # Last resort: never emit a dynamic payload that still carries a secret.
        return json.dumps({SANITIZATION_KEY: SANITIZATION_MARKER}), False
    return redacted, False


def artifacts_with_secrets(directory: Path, secrets: Sequence[str]) -> list[str]:
    """Second, independent layer: re-read the bytes that reached the disk."""
    variants = secret_variants(secrets)
    leaked: list[str] = []
    for name in ARTIFACT_NAMES:
        path = Path(directory) / name
        if path.is_file() and contains_secret(path.read_bytes(), variants):
            leaked.append(name)
    return leaked


def write_evidence(directory: Path, evidence: RunEvidence) -> Path:
    """Write the sanitized JSON report and Markdown summary for one run.

    Both artifacts are serialized in memory, verified against the run secrets
    and only then written: a secret is never written to disk, not even to be
    replaced afterwards. When a leak is detected the text is redacted in
    memory, the run is marked as a sanitization failure and the result is
    downgraded, so the artifacts never claim a hygiene the run did not have.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    secrets = secret_variants(evidence.secrets)
    if secrets and evidence.hygiene != FAIL:
        evidence.hygiene = PASS
    artifacts = _render_artifacts(evidence)
    leaks = [name for name, text in artifacts.items() if contains_secret(text, secrets)]
    if leaks:
        evidence.hygiene = FAIL
        for name in leaks:
            evidence.sanitization_failures.append(f"{name} carried a run secret before writing")
        artifacts = _render_artifacts(evidence)
        artifacts = {name: scrub_text(text, secrets) for name, text in artifacts.items()}
    for name, text in artifacts.items():
        (directory / name).write_text(text, encoding="utf-8")
    reread = artifacts_with_secrets(directory, secrets) if secrets else []
    if reread:
        # Safety net for the written bytes: repair them before the run reports.
        evidence.hygiene = FAIL
        for name in reread:
            evidence.sanitization_failures.append(f"{name} carried a run secret after writing")
        artifacts = {
            name: scrub_text(text, secrets)
            for name, text in _render_artifacts(evidence).items()
        }
        for name, text in artifacts.items():
            (directory / name).write_text(text, encoding="utf-8")
    return directory / "report.json"


# ---------------------------------------------------------------------------
# Expected synthetic descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CensusFilterExpectation:
    query: Mapping[str, str]
    expect_registro: str
    expect_nome: str
    expect_rows: int


@dataclass(frozen=True)
class Expectations:
    census_filter: CensusFilterExpectation | None = None
    reason: str = "expectations not provided"


def load_expectations(path: str | None) -> Expectations:
    """Load the operator-supplied descriptor; never invent one."""
    if not path:
        return Expectations()
    try:
        raw = json.loads(Path(path).read_text())
    except OSError:
        return Expectations(reason=f"expectations unreadable: {path}")
    except ValueError:
        return Expectations(reason=f"expectations invalid: {path}")
    if not isinstance(raw, dict):
        return Expectations(reason=f"expectations invalid: {path}")
    census = raw.get("census_filter")
    if not isinstance(census, dict):
        return Expectations(reason=f"expectations invalid: census_filter missing in {path}")
    query_raw = census.get("query")
    if not isinstance(query_raw, dict):
        return Expectations(reason=f"expectations invalid: census_filter.query missing in {path}")
    query: dict[str, str] = {}
    for key, value in query_raw.items():
        if key not in QUERY_KEYS or not isinstance(value, str):
            return Expectations(reason=f"expectations invalid: unsupported census query key {key}")
        query[key] = value
    registro = census.get("expect_registro")
    nome = census.get("expect_nome")
    rows = census.get("expect_rows")
    if not isinstance(registro, str) or not registro.strip():
        return Expectations(reason=f"expectations invalid: expect_registro missing in {path}")
    if not isinstance(nome, str) or not nome.strip():
        return Expectations(reason=f"expectations invalid: expect_nome missing in {path}")
    if type(rows) is not int or rows < 0:
        return Expectations(reason=f"expectations invalid: expect_rows missing in {path}")
    return Expectations(
        census_filter=CensusFilterExpectation(
            query=query, expect_registro=registro, expect_nome=nome, expect_rows=rows
        ),
        reason="",
    )


# ---------------------------------------------------------------------------
# Journey context
# ---------------------------------------------------------------------------


@dataclass
class JourneyContext:
    role: str
    viewport: Viewport
    page: Any
    context: Any
    observations: Observations
    expectations: Expectations
    base_url: str
    evidence: RunEvidence
    evidence_dir: Path
    timeout_ms: int
    required_assets: tuple[str, ...] = ()
    credentials: Mapping[str, str] = field(default_factory=dict)

    def credential(self) -> tuple[str, str]:
        username = OWNED_USERNAMES.get(self.role)
        if username is None:
            raise DriverBlocked(f"no owned username for role {self.role}")
        password = self.credentials.get(username)
        if not password:
            raise DriverBlocked("no in-memory credential for this role")
        return username, password

    def screenshot(self, name: str) -> str:
        relative = f"screenshots/{self.role}-{self.viewport.name}-{name}.png"
        target = self.evidence_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(target))
        if relative not in self.evidence.screenshots:
            self.evidence.screenshots.append(relative)
        return relative


def required_assets_for(case_ids: Iterable[str], base_url: str) -> tuple[str, ...]:
    assets = [f"{base_url}/static/css/sirhosp.css", *REQUIRED_ASSETS]
    if any(case_id in CENSUS_CASE_IDS for case_id in case_ids):
        assets.extend(CENSUS_REQUIRED_ASSETS)
    return tuple(assets)


# ---------------------------------------------------------------------------
# Journeys
# ---------------------------------------------------------------------------


def _goto(ctx: JourneyContext, path: str) -> None:
    ctx.page.goto(ctx.base_url + path, wait_until="load", timeout=ctx.timeout_ms)


def _wait_for_path(ctx: JourneyContext, path: str) -> None:
    ctx.page.wait_for_url(lambda url: urlsplit(url).path == path, timeout=ctx.timeout_ms)


def _nav_links(ctx: JourneyContext) -> list[dict]:
    links = ctx.page.evaluate(
        "() => Array.from(document.querySelectorAll('#sidebar .sirhosp-sidebar-link'))"
        ".map(a => ({text: a.textContent.trim(),"
        " href: a.getAttribute('href'), active: a.classList.contains('active')}))"
    )
    if not isinstance(links, list):
        raise DriverBlocked("sidebar navigation could not be read")
    return links


def _tomselect_pick(ctx: JourneyContext, select_id: str, value: str) -> None:
    ctx.page.click(f"#{select_id} + .ts-wrapper .ts-control")
    ctx.page.wait_for_selector(".ts-dropdown .option", state="visible", timeout=ctx.timeout_ms)
    index = ctx.page.evaluate(
        "v => Array.from(document.querySelectorAll('.ts-dropdown .option'))"
        ".findIndex(o => o.getAttribute('data-value') === v)",
        value,
    )
    if not isinstance(index, int) or index < 0:
        raise AssertionError(f"TomSelect did not offer {value!r} for #{select_id}")
    ctx.page.locator(".ts-dropdown .option").nth(index).click()


def case_login(ctx: JourneyContext) -> CaseOutcome:
    username, password = ctx.credential()
    _goto(ctx, "/login/")
    if ctx.page.locator("#id_username").count() != 1:
        raise AssertionError("login form is missing #id_username")
    if ctx.page.locator("#id_password").count() != 1:
        raise AssertionError("login form is missing #id_password")
    shot = ctx.screenshot("login-form")
    # Screenshot taken before any credential is typed; the password only
    # ever lives in the DOM of this password field.
    ctx.page.fill("#id_username", username)
    ctx.page.fill("#id_password", password)
    ctx.page.click("form button[type=submit]")
    _wait_for_path(ctx, "/painel/")
    if ctx.page.locator("#sidebar .sirhosp-sidebar-footer").count() != 1:
        raise AssertionError("authenticated shell did not render after login")
    return CaseOutcome(
        PASS,
        f"real form login reached /painel/ as {username}",
        (shot,),
    )


def case_shell(ctx: JourneyContext) -> CaseOutcome:
    _goto(ctx, "/painel/")
    links = _nav_links(ctx)
    texts = [str(link["text"]) for link in links]
    for expected in ("Dashboard", "Censo"):
        if expected not in texts:
            raise AssertionError(f"sidebar is missing the {expected} link")
    censo = next(link for link in links if link["text"] == "Censo")
    if censo["href"] != "/censo/":
        raise AssertionError(f"Censo link points at {censo['href']!r}")
    profile = ctx.page.locator("#sidebar .sirhosp-sidebar-footer a").filter(has_text="Perfil")
    if profile.count() != 1:
        raise AssertionError("sidebar footer is missing the Perfil link")
    if profile.first.get_attribute("href") != "/perfil/":
        raise AssertionError("Perfil link does not point at /perfil/")
    username = OWNED_USERNAMES[ctx.role]
    footer = ctx.page.locator("#sidebar .sirhosp-sidebar-footer").inner_text()
    if username not in footer:
        raise AssertionError("sidebar footer does not show the authenticated identity")
    active = [str(link["text"]) for link in links if link["active"]]
    if active != ["Dashboard"]:
        raise AssertionError(f"unexpected active menu {active}")
    shot = ctx.screenshot("panel")
    return CaseOutcome(PASS, f"identity {username}; active menu Dashboard", (shot,))


def case_role_visibility(ctx: JourneyContext) -> CaseOutcome:
    links = _nav_links(ctx)
    statistics = [link for link in links if link["text"] == "Estatísticas"]
    if ctx.role == "user":
        if statistics:
            raise AssertionError("the common role must not see the Estatísticas item")
        return CaseOutcome(PASS, "Estatísticas absent for the common role")
    if len(statistics) != 1:
        raise AssertionError("the admin role must see exactly one Estatísticas item")
    if statistics[0]["href"] != "/statistics/":
        raise AssertionError(f"Estatísticas link points at {statistics[0]['href']!r}")
    return CaseOutcome(PASS, "Estatísticas visible for the admin role; no export was visited")


def case_census_tomselect(ctx: JourneyContext) -> CaseOutcome:
    _goto(ctx, "/censo/")
    if ctx.page.locator("#unidade").count() != 1:
        raise AssertionError("census filter #unidade is missing")
    if not ctx.page.evaluate(
        "() => !!(document.getElementById('unidade')"
        " && document.getElementById('unidade').tomselect)"
    ):
        raise AssertionError("TomSelect did not initialize on #unidade")
    options = ctx.page.evaluate(
        "() => Array.from(document.querySelectorAll('#unidade option'))"
        ".map(o => o.value).filter(v => v)"
    )
    if not isinstance(options, list) or not options:
        raise DriverBlocked("the confirmed dataset offers no unit option to filter by")
    before = ctx.screenshot("censo-filters")
    value = str(options[0])
    _tomselect_pick(ctx, "unidade", value)
    if ctx.page.input_value("#unidade") != value:
        raise AssertionError("TomSelect selection was not kept in the underlying select")
    ctx.page.click("form[method=get] button[type=submit]")
    _wait_for_path(ctx, "/censo/")
    selected = ctx.page.evaluate("() => document.getElementById('unidade').value")
    if selected != value:
        raise AssertionError("the unit selection was not preserved after filtering")
    if not ctx.page.evaluate("() => !!(document.getElementById('unidade').tomselect)"):
        raise AssertionError("TomSelect did not re-initialize after filtering")
    after = ctx.screenshot("censo-filtered")
    return CaseOutcome(
        PASS,
        f"TomSelect initialized, picked {value!r} through the UI and kept it after submit",
        (before, after),
    )


def case_census_filter_positive(ctx: JourneyContext) -> CaseOutcome:
    expectation = ctx.expectations.census_filter
    if expectation is None:
        return CaseOutcome(BLOCKED, ctx.expectations.reason or "expectations not provided")
    _goto(ctx, "/censo/")
    for key, value in expectation.query.items():
        if not value:
            continue
        if key == "q":
            ctx.page.fill("#q", value)
        elif key in {"unidade", "especialidade"}:
            _tomselect_pick(ctx, key, value)
        else:
            ctx.page.select_option(f"#{key}", value)
    ctx.page.click("form[method=get] button[type=submit]")
    _wait_for_path(ctx, "/censo/")
    rows = ctx.page.evaluate(
        "() => Array.from(document.querySelectorAll('table tbody tr'))"
        ".map(tr => Array.from(tr.querySelectorAll('td')).map(td => td.textContent.trim()))"
    )
    if not isinstance(rows, list):
        raise AssertionError("filtered census rows could not be read")
    matched = [
        row
        for row in rows
        if len(row) > 1
        and expectation.expect_registro in row[0]
        and expectation.expect_nome in row[1]
    ]
    if len(rows) != expectation.expect_rows:
        raise AssertionError(f"expected {expectation.expect_rows} rows, observed {len(rows)}")
    if not matched:
        raise AssertionError("the expected synthetic descriptor is not in the filtered result")
    shot = ctx.screenshot("censo-positive")
    return CaseOutcome(
        PASS, f"filtered result matches the descriptor ({len(rows)} row(s))", (shot,)
    )


def case_topbar_polls(ctx: JourneyContext) -> CaseOutcome:
    _goto(ctx, "/painel/")
    if ctx.page.locator(".sirhosp-topbar-sync").count() != 1:
        raise AssertionError("expected exactly one sync badge before polling")
    badge_url = ctx.base_url + HTMX_BADGE_PATH
    evidence = []
    for index in range(POLL_COUNT):
        response = ctx.page.wait_for_event(
            "response",
            predicate=lambda candidate: candidate.url.startswith(badge_url)
            and candidate.request.method == "GET",
            timeout=POLL_TIMEOUT_MS,
        )
        if response.status != 200:
            raise AssertionError(f"badge poll {index + 1} returned HTTP {response.status}")
        body = response.text()
        if "csrfmiddlewaretoken" in body or "<form" in body or "id_password" in body:
            raise AssertionError(f"badge poll {index + 1} fragment carries a login form")
        if ctx.page.locator(".sirhosp-topbar-sync").count() != 1:
            raise AssertionError("the sync badge was duplicated by the swap")
        attributes = ctx.page.evaluate(
            "() => { const el = document.querySelector('.sirhosp-topbar-sync');"
            " if (!el) return null;"
            " return {get: el.getAttribute('hx-get'), swap: el.getAttribute('hx-swap'),"
            " trigger: el.getAttribute('hx-trigger')}; }"
        )
        if (
            not attributes
            or attributes.get("trigger") != "every 60s"
            or attributes.get("swap") != "outerHTML"
        ):
            raise AssertionError("the sync badge did not re-arm itself after the swap")
        evidence.append(f"poll {index + 1}: HTTP {response.status} {sanitize_url(response.url)}")
    return CaseOutcome(PASS, f"{POLL_COUNT} real HTMX polls observed", tuple(evidence))


def case_mobile_nav(ctx: JourneyContext) -> CaseOutcome:
    if ctx.viewport.name != MOBILE.name:
        return CaseOutcome(SKIPPED, "the mobile menu only applies to the mobile viewport")
    _goto(ctx, "/painel/")

    def sidebar_state() -> dict:
        return ctx.page.evaluate(
            "() => ({open: document.getElementById('sidebar').classList.contains('open'),"
            " overlay: document.getElementById('sidebarOverlay').classList.contains('show'),"
            " left: document.getElementById('sidebar').getBoundingClientRect().left})"
        )

    def overflow() -> float:
        return ctx.page.evaluate(
            "() => document.documentElement.scrollWidth - window.innerWidth"
        )

    state = sidebar_state()
    if state["open"]:
        raise AssertionError("the mobile sidebar starts open")
    if overflow() > 2:
        raise AssertionError("unexpected horizontal overflow before opening the menu")
    ctx.page.click("#sidebarToggle")
    ctx.page.wait_for_function(
        "() => document.getElementById('sidebar').getBoundingClientRect().left >= 0",
        timeout=ctx.timeout_ms,
    )
    state = sidebar_state()
    if not state["overlay"]:
        raise AssertionError("the sidebar overlay did not appear with the menu")
    shot = ctx.screenshot("mobile-menu-open")
    ctx.page.keyboard.press("Escape")
    ctx.page.wait_for_function(
        "() => !document.getElementById('sidebar').classList.contains('open')",
        timeout=ctx.timeout_ms,
    )
    ctx.page.click("#sidebarToggle")
    if not sidebar_state()["open"]:
        raise AssertionError("the menu did not reopen on a second toggle")
    ctx.page.click("#sidebarOverlay")
    state = sidebar_state()
    if state["open"] or state["overlay"]:
        raise AssertionError("clicking the overlay did not close the menu")
    if overflow() > 2:
        raise AssertionError("unexpected horizontal overflow after closing the menu")
    return CaseOutcome(
        PASS,
        "mobile menu opened and closed through the toggle, the overlay and Escape",
        (shot,),
    )


def case_logout(ctx: JourneyContext) -> CaseOutcome:
    if ctx.viewport.name == MOBILE.name:
        # The sidebar is off-canvas at this width; the Sair button is only
        # reachable after the menu is opened, exactly as a user would do.
        ctx.page.click("#sidebarToggle")
        ctx.page.wait_for_function(
            "() => document.getElementById('sidebar').getBoundingClientRect().left >= 0",
            timeout=ctx.timeout_ms,
        )
    form = ctx.page.locator("#sidebar form[action='/logout/']")
    if form.count() != 1:
        raise AssertionError("logout form is missing from the sidebar")
    form.locator("button").click()
    _wait_for_path(ctx, "/")
    _goto(ctx, "/painel/")
    if "/login/" not in ctx.page.url:
        raise AssertionError("a protected page is still reachable after logout")
    shot = ctx.screenshot("after-logout")
    return CaseOutcome(
        PASS,
        "logout button ended the session; /painel/ redirects to the login route",
        (shot,),
    )


def case_required_assets(ctx: JourneyContext) -> CaseOutcome:
    missing = ctx.observations.missing_assets(ctx.required_assets)
    observed = len(ctx.observations.observed_assets)
    if missing:
        return CaseOutcome(
            FAIL,
            f"required assets missing: {', '.join(missing)}",
            (f"{observed} asset responses observed",),
        )
    return CaseOutcome(
        PASS,
        f"{len(ctx.required_assets)} required assets answered with HTTP 200",
        (f"{observed} asset responses observed",),
    )


def case_policy_allowlist(ctx: JourneyContext) -> CaseOutcome:
    probes: list[tuple[str, str, str]] = [
        (f"{ctx.base_url}/ingestao/sincronizar-demograficos/", "GET", "demographics enqueue"),
        (f"{ctx.base_url}/ingestao/criar/", "GET", "ingestion run creation"),
        (f"{ctx.base_url}/censo/exportar/", "GET", "census export"),
        (f"{ctx.base_url}/statistics/export/", "GET", "statistics export"),
        ("https://evil.example/steal", "GET", "external redirect target"),
    ]
    if ctx.base_url.startswith("https://"):
        # The canonical verification origin is https: the same host over
        # plain http must be refused. Native http loopback contexts skip
        # this probe because http is their own authorized scheme.
        probes.append((f"http{ctx.base_url[5:]}/painel/", "GET", "insecure scheme"))
    evidence = []
    for url, method, label in probes:
        decision = ctx.observations.policy.decide(url, method)
        if decision.allowed:
            raise AssertionError(f"{label} was not refused: {method} {sanitize_url(url)}")
        evidence.append(f"refused {label}: {method} {sanitize_url(url)} ({decision.reason})")
    for url, method in ((f"{ctx.base_url}/login/", "POST"), (f"{ctx.base_url}/logout/", "POST")):
        if not ctx.observations.policy.decide(url, method).allowed:
            raise AssertionError(f"authentication route refused: {method} {sanitize_url(url)}")
    blocked_before = len(ctx.observations.expected_blocks)
    blocked_url = (
        f"{ctx.base_url}/ingestao/sincronizar-demograficos/?patient_record=VFYS2-POLICY-PROBE"
    )
    try:
        ctx.page.goto(blocked_url, wait_until="load", timeout=ctx.timeout_ms)
    except Exception:  # the browser aborts the navigation itself
        pass
    else:
        raise AssertionError("a policy-refused navigation completed")
    if len(ctx.observations.expected_blocks) <= blocked_before:
        raise AssertionError("the refused navigation was not recorded by the request policy")
    evidence.append("browser navigation to the demographics enqueue route was aborted")
    return CaseOutcome(
        PASS,
        "allowlist refused every business mutation probe before any effect",
        tuple(evidence),
    )


CaseRunner = Callable[[JourneyContext], CaseOutcome]
CasePlan = tuple[tuple[str, CaseRunner], ...]

POLICY_CASES: CasePlan = (("policy-allowlist", case_policy_allowlist),)

_SHELL_CASES: CasePlan = (
    ("auth-login", case_login),
    ("auth-shell", case_shell),
    ("auth-visibility", case_role_visibility),
)
_TAIL_CASES: CasePlan = (
    ("auth-logout", case_logout),
    ("assets-required", case_required_assets),
)


def case_plan(feature: str, viewport: Viewport) -> CasePlan:
    if feature == "auth":
        return _SHELL_CASES + _TAIL_CASES
    if feature != "smoke":
        raise DriverBlocked(f"unknown feature {feature}")
    if viewport.name == MOBILE.name:
        extras: CasePlan = (("mobile-nav", case_mobile_nav),)
    else:
        extras = (("topbar-polls", case_topbar_polls),)
    return (
        _SHELL_CASES
        + (
            ("census-tomselect", case_census_tomselect),
            ("census-filter-positive", case_census_filter_positive),
        )
        + extras
        + _TAIL_CASES
    )


# ---------------------------------------------------------------------------
# Driver orchestration
# ---------------------------------------------------------------------------


def _clip(text: object, limit: int = 400) -> str:
    flat = " ".join(str(text).split())
    if len(flat) <= limit:
        return flat
    return flat[:limit] + "…"


def _classify(case_id: str, role: str, viewport: str, exc: BaseException) -> CaseResult:
    if isinstance(exc, DriverBlocked):
        return CaseResult(case_id, role, viewport, BLOCKED, _clip(exc))
    if isinstance(exc, DriverTimeout) or "Timeout" in type(exc).__name__:
        return CaseResult(case_id, role, viewport, FAIL, f"timeout: {_clip(exc)}")
    if isinstance(exc, AssertionError):
        return CaseResult(case_id, role, viewport, FAIL, f"assertion failed: {_clip(exc)}")
    return CaseResult(case_id, role, viewport, FAIL, f"{type(exc).__name__}: {_clip(exc)}")


def _merge_observations(evidence: RunEvidence, observations: Observations) -> None:
    evidence.request_violations.extend(observations.violations)
    # Popups and websockets are never expected by a journey: they are violations
    # of the same boundary and fail the run.
    evidence.request_violations.extend(observations.popup_blocks)
    evidence.request_violations.extend(observations.websocket_blocks)
    _extend_unique(evidence.deliberate_blocks, observations.expected_blocks)
    _extend_unique(evidence.edge_blocks, observations.edge_blocks)
    evidence.js_errors.extend(observations.js_errors)
    evidence.http_unexpected.extend(observations.http_unexpected)
    evidence.failed_requests.extend(observations.failed_requests)
    for asset in sorted(observations.observed_assets):
        if asset not in evidence.assets:
            evidence.assets.append(asset)


def _extend_unique(target: list[str], entries: Iterable[str]) -> None:
    for entry in entries:
        if entry not in target:
            target.append(entry)


class SmokeDriver:
    """Runs the requested journeys and fills one ``RunEvidence`` per run."""

    def __init__(
        self,
        *,
        session: Any,
        evidence_dir: Path,
        expectations: Expectations | None = None,
        base_url: str,
        timeout_ms: int = 20000,
        case_table: Callable[[str, Viewport], CasePlan] | None = None,
        policy_case_table: Callable[[str, Viewport], CasePlan] | None = None,
        queue_probe: Callable[[], Mapping[str, int]] | None = None,
        credentials: Mapping[str, str] | None = None,
        redactions: Sequence[str] = (),
    ) -> None:
        self.session = session
        self.evidence_dir = Path(evidence_dir)
        self.expectations = expectations or Expectations()
        self.base_url = base_url
        self.timeout_ms = timeout_ms
        self.queue_probe = queue_probe
        self.credentials = dict(credentials or {})
        self.redactions = tuple(redactions)
        self.policy = RequestPolicy(origin=base_url)
        self._case_table = case_table
        self._policy_case_table = policy_case_table
        # Set when a group reports a fatal release failure: the remaining
        # groups must not run, so the owned browser is closed immediately.
        self._fatal = False

    def plan(self, feature: str, viewport: Viewport) -> CasePlan:
        if self._case_table is not None:
            return self._case_table(feature, viewport)
        return case_plan(feature, viewport)

    def policy_plan(self, feature: str, viewport: Viewport) -> CasePlan:
        if self._policy_case_table is not None:
            return self._policy_case_table(feature, viewport)
        return POLICY_CASES

    def execute(
        self,
        evidence: RunEvidence,
        *,
        feature: str,
        roles: Sequence[str],
        viewports: Sequence[Viewport],
        inject_failure: str | None = None,
    ) -> None:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence.secrets = tuple(self.redactions)
        before = self._queue_snapshot(evidence)
        for role in roles:
            for viewport in viewports:
                if self._fatal:
                    break
                self._run_group(
                    evidence,
                    role=role,
                    viewport=viewport,
                    cases=self.plan(feature, viewport),
                    expect_blocks=False,
                )
            if self._fatal:
                break
        if viewports and not self._fatal:
            self._run_group(
                evidence,
                role="both",
                viewport=viewports[0],
                cases=self.policy_plan(feature, viewports[0]),
                expect_blocks=True,
            )
        self._queue_diff(evidence, before)
        if inject_failure == "assert":
            raise AssertionError("injected controlled failure: assertion")
        if inject_failure == "timeout":
            raise DriverTimeout("injected controlled failure: timeout")

    def close_browser(self) -> str | None:
        try:
            self.session.close()
        except Exception as exc:  # cleanup failure must stay visible, not crash
            return f"browser close failed: {exc}"
        return None

    def _queue_snapshot(self, evidence: RunEvidence) -> dict[str, int] | None:
        if self.queue_probe is None:
            return None
        try:
            return dict(self.queue_probe())
        except Exception as exc:
            evidence.cases.append(
                CaseResult("queue-metadata", "both", "-", FAIL, f"queue probe failed: {exc}")
            )
            return None

    def _queue_diff(self, evidence: RunEvidence, before: dict[str, int] | None) -> None:
        if before is None or self.queue_probe is None:
            return
        try:
            after = dict(self.queue_probe())
        except Exception as exc:
            evidence.cases.append(
                CaseResult("queue-metadata", "both", "-", FAIL, f"queue probe failed: {exc}")
            )
            return
        clean, changes = compare_queue_metadata(before, after)
        evidence.queue_changes.extend(changes)
        evidence.cases.append(
            CaseResult(
                "queue-metadata",
                "both",
                "-",
                PASS if clean else FAIL,
                "no queue metadata change" if clean else "; ".join(changes),
            )
        )

    def _run_group(
        self,
        evidence: RunEvidence,
        *,
        role: str,
        viewport: Viewport,
        cases: CasePlan,
        expect_blocks: bool,
    ) -> None:
        observations = Observations(
            self.policy, expect_blocks=expect_blocks, redactions=self.redactions
        )
        handle = self.session.new_role_context(
            role=role, viewport=viewport, observations=observations
        )
        ctx = JourneyContext(
            role=role,
            viewport=viewport,
            page=handle.page,
            context=getattr(handle, "context", None),
            observations=observations,
            expectations=self.expectations,
            base_url=self.base_url,
            evidence=evidence,
            evidence_dir=self.evidence_dir,
            timeout_ms=self.timeout_ms,
            required_assets=required_assets_for((case_id for case_id, _ in cases), self.base_url),
            credentials=self.credentials,
        )
        try:
            for case_id, runner in cases:
                if observations.fatal:
                    break
                try:
                    outcome = runner(ctx)
                except Exception as exc:
                    evidence.cases.append(_classify(case_id, role, viewport.name, exc))
                else:
                    evidence.cases.append(
                        CaseResult(
                            case_id,
                            role,
                            viewport.name,
                            outcome.status,
                            outcome.detail,
                            tuple(outcome.evidence),
                        )
                    )
            if observations.fatal:
                self._fatal = True
        finally:
            _merge_observations(evidence, observations)
            try:
                handle.close()
            except Exception as exc:
                evidence.cases.append(
                    CaseResult(
                        f"context-close-{role}-{viewport.name}",
                        role,
                        viewport.name,
                        FAIL,
                        f"context close failed: {exc}",
                    )
                )


# ---------------------------------------------------------------------------
# Real Playwright session
# ---------------------------------------------------------------------------


@dataclass
class _RoleContext:
    page: Any
    context: Any

    def close(self) -> None:
        self.context.close()


def _attach_page_observers(page: Any, observations: Observations) -> None:
    def on_console(message: Any) -> None:
        observations.note_console(message.type, message.text)

    def on_page_error(error: Any) -> None:
        observations.note_page_error(str(error))

    def on_response(response: Any) -> None:
        observations.note_response(response.url, response.status)

    def on_request_failed(request: Any) -> None:
        observations.note_request_failed(request.url, str(request.failure or ""))

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("response", on_response)
    page.on("requestfailed", on_request_failed)


def _request_page(request: Any) -> Any | None:
    """The page a request belongs to; ``None`` when Playwright cannot say."""
    try:
        return request.frame.page
    except Exception:
        return None


def _page_has_hop_layer(request: Any, covered_pages: Sequence[Any]) -> bool:
    page = _request_page(request)
    return page is not None and any(page is candidate for candidate in covered_pages)


def _attach_cdp_hop_layer(
    context: Any, page: Any, observations: Observations, covered_pages: list[Any]
) -> None:
    """Per-page CDP layer: every request, redirect hops included, is decided
    before it reaches the wire, so a refused hop never opens a connection."""
    try:
        client = context.new_cdp_session(page)
        client.send(
            "Fetch.enable",
            {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]},
        )
    except Exception as exc:
        # Without the hop layer the policy cannot claim to stop redirects, so
        # the run must not be able to report PASS.
        observations.violations.append(
            f"cdp hop layer unavailable: {type(exc).__name__}: {exc}"
        )
        return

    def on_request_paused(params: Mapping[str, Any]) -> None:
        request = params.get("request") or {}
        url = str(request.get("url", ""))
        method = str(request.get("method", "GET"))
        decision = observations.decide(url, method)
        try:
            if decision.allowed:
                client.send("Fetch.continueRequest", {"requestId": params["requestId"]})
            else:
                client.send(
                    "Fetch.failRequest",
                    {"requestId": params["requestId"], "errorReason": "Aborted"},
                )
        except Exception as exc:
            # Either CDP response can fail and leave the request paused: the
            # interception is compromised, so the violation below forces the
            # run to FAIL through the existing aggregation. Signal the run
            # fatal synchronously, before the best-effort release below can
            # suspend and let the next case start.
            action = "continueRequest" if decision.allowed else "failRequest"
            observations.violations.append(
                f"cdp {action} failed for {sanitize_url(url)}: {type(exc).__name__}: {exc}"
            )
            observations.fatal = True
            # Best effort release: detach the CDP session, then close the owned
            # context so a paused request is not left hanging. Whether Chromium
            # resolves a paused request when its session detaches is not
            # guaranteed by Playwright; the only observed effect is the absence
            # of further transport for a refused request.
            try:
                client.detach()
            except Exception:
                pass
            try:
                context.close()
            except Exception as exc_close:
                # A failed release must stay visible: without this violation
                # nobody would know the resource was not released. The run is
                # already fatal from the action failure above.
                observations.violations.append(
                    f"cdp release failed for {sanitize_url(url)}: "
                    f"{type(exc_close).__name__}: {exc_close}"
                )

    client.on("Fetch.requestPaused", on_request_paused)
    covered_pages.append(page)


class PlaywrightBrowser:
    """Owned headless Chromium session; always started headless."""

    def __init__(
        self, *, base_url: str, headless: bool = True, timeout_ms: int = 20000
    ) -> None:
        self.base_url = base_url
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._playwright: Any = None
        self._browser: Any = None
        self._closed = False

    def _ensure_started(self) -> None:
        if self._browser is not None:
            return
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)

    def new_role_context(
        self, *, role: str, viewport: Viewport, observations: Observations
    ) -> _RoleContext:
        self._ensure_started()
        context = self._browser.new_context(
            viewport={"width": viewport.width, "height": viewport.height},
            # A service worker would answer requests below the routing and CDP
            # layers; the journeys need none and the portal has no script that
            # requires one.
            service_workers="block",
        )
        context.set_default_timeout(self.timeout_ms)
        # The journeys never expect a popup, so an unexpected one is stopped at
        # its source instead of being navigated somewhere in this context.
        context.add_init_script(POPUP_GUARD_SCRIPT)
        # Only the pages the driver creates carry the CDP hop layer; any other
        # page (an unforeseen popup) is still covered by the context route.
        covered_pages: list[Any] = []

        def handle_route(route: Any) -> None:
            request = route.request
            if _page_has_hop_layer(request, covered_pages):
                # The CDP layer records the decision for owned pages: recording
                # it here as well would report one request twice.
                decision = observations.policy.decide(request.url, request.method)
            else:
                decision = observations.decide(request.url, request.method)
            try:
                if decision.allowed:
                    route.continue_()
                else:
                    route.abort()
            except Exception:
                # The CDP layer may have handled this request already.
                pass

        def handle_websocket(websocket_route: Any) -> None:
            # Passive handler: without connect_to_server the handshake never
            # leaves the browser and the destination sees no connection.
            observations.note_websocket_attempt(websocket_route.url)

        def handle_new_page(new_page: Any) -> None:
            observations.note_popup_page(str(getattr(new_page, "url", "")))
            _attach_page_observers(new_page, observations)

        context.route("**/*", handle_route)
        # A wide pattern is required: ``ws://**`` and ``wss://**`` do not match
        # websocket upgrades in the installed Playwright version.
        context.route_web_socket("**/*", handle_websocket)
        page = context.new_page()
        _attach_page_observers(page, observations)
        _attach_cdp_hop_layer(context, page, observations, covered_pages)
        context.on("page", handle_new_page)
        return _RoleContext(page=page, context=context)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._browser is not None:
            try:
                self._browser.close()
            finally:
                self._browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            finally:
                self._playwright = None
