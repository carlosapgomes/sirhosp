"""S2 contracts: request policy, evidence, prerequisites, aggregation, cleanup.

These tests drive the repeatable runner with fake pages and sessions. They are
tests of the runner, not proof that the portal UI works; the real headless
browser run is the product proof.
"""

from __future__ import annotations

import importlib
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote

import pytest

from automation.verification import browser

RUN = "a" * 32
ORIGIN = "https://portal-dev.verification.invalid"


@pytest.fixture
def controller():
    return importlib.import_module("scripts.verify_portal")


# ---------------------------------------------------------------------------
# R5 — request allowlist by origin, method and path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["/", "/login/", "/logout/", "/painel/", "/censo/", "/perfil/", "/atualizacao-censo/"]
)
def test_policy_allows_shell_read_paths(path):
    decision = browser.RequestPolicy(origin=ORIGIN).decide(f"{ORIGIN}{path}", "GET")
    assert decision.allowed is True
    assert decision.category == "allowed"


@pytest.mark.parametrize(
    "path",
    [
        "/ingestao/criar/",
        "/ingestao/sincronizar-internacoes/",
        "/ingestao/sincronizar-demograficos/",
        "/censo/exportar/",
        "/statistics/export/",
        "/reconciliacao/exportar/",
        "/ingestao/status/7/",
        "/admin/",
    ],
)
def test_policy_blocks_business_and_mutating_get_routes(path):
    decision = browser.RequestPolicy(origin=ORIGIN).decide(f"{ORIGIN}{path}", "GET")
    assert decision.allowed is False
    assert decision.category == "policy"
    assert decision.reason


def test_policy_allows_only_login_and_logout_posts():
    policy = browser.RequestPolicy(origin=ORIGIN)
    assert policy.decide(f"{ORIGIN}/login/", "POST").allowed is True
    assert policy.decide(f"{ORIGIN}/logout/", "POST").allowed is True
    for path in ("/painel/", "/censo/", "/perfil/", "/ingestao/criar/"):
        assert policy.decide(f"{ORIGIN}{path}", "POST").allowed is False


def test_policy_blocks_external_redirect_and_popup_targets():
    policy = browser.RequestPolicy(origin=ORIGIN)
    for url in (
        "https://evil.example/portal",
        "https://portal-dev.verification.invalid.evil.example/painel/",
        "https://other.invalid/?next=/painel/",
    ):
        assert policy.decide(url, "GET").allowed is False


def test_policy_blocks_insecure_scheme():
    decision = browser.RequestPolicy(origin=ORIGIN).decide(
        ORIGIN.replace("https://", "http://") + "/painel/", "GET"
    )
    assert decision.allowed is False


def test_policy_allows_static_assets_and_ignores_favicon():
    policy = browser.RequestPolicy(origin=ORIGIN)
    assert policy.decide(f"{ORIGIN}/static/css/sirhosp.css", "GET").allowed is True
    favicon = policy.decide(f"{ORIGIN}/favicon.ico", "GET")
    assert favicon.allowed is True
    assert favicon.category == "ignored"


def test_policy_allows_only_known_versioned_cdn_paths():
    policy = browser.RequestPolicy(origin=ORIGIN)
    for url in (
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css",
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css",
        "https://cdn.jsdelivr.net/npm/tom-select@2.3.1/dist/js/tom-select.complete.min.js",
        "https://unpkg.com/htmx.org@2.0.4",
        "https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js",
    ):
        assert policy.decide(url, "GET").allowed is True, url
    for url in (
        "https://cdn.jsdelivr.net/",
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js.bak",
        "https://cdn.jsdelivr.net/npm/bootstrap@5.4.0/dist/css/bootstrap.min.css",
        "https://unpkg.com/",
        "https://unpkg.com/htmx.org@2.0.4/../evil.js",
        "https://cdn.example.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css",
    ):
        assert policy.decide(url, "GET").allowed is False, url
    assert (
        policy.decide(
            "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/"
            "bootstrap-icons.woff2?dd67030699838ea613ee6dbda90effa6",
            "GET",
        ).allowed
        is True
    )


def test_policy_blocks_cdn_posts():
    policy = browser.RequestPolicy(origin=ORIGIN)
    decision = policy.decide(
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css", "POST"
    )
    assert decision.allowed is False


def test_policy_blocks_portal_origin_with_non_default_port():
    decision = browser.RequestPolicy(origin=ORIGIN).decide(
        "https://portal-dev.verification.invalid:444/painel/", "GET"
    )
    assert decision.allowed is False
    assert decision.category == "policy"
    assert decision.reason


def test_policy_blocks_cdn_origin_with_non_default_port():
    decision = browser.RequestPolicy(origin=ORIGIN).decide(
        "https://cdn.jsdelivr.net:8443/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css", "GET"
    )
    assert decision.allowed is False
    assert decision.category == "policy"
    assert decision.reason


def test_policy_allows_default_and_explicit_default_port_origins():
    policy = browser.RequestPolicy(origin=ORIGIN)
    assert policy.decide(f"{ORIGIN}/painel/", "GET").allowed is True
    assert policy.decide("https://portal-dev.verification.invalid:443/painel/", "GET").allowed is True
    assert (
        policy.decide(
            "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css", "GET"
        ).allowed
        is True
    )
    assert (
        policy.decide(
            "https://cdn.jsdelivr.net:443/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css", "GET"
        ).allowed
        is True
    )


def test_policy_classifies_edge_telemetry_separately():
    policy = browser.RequestPolicy(origin=ORIGIN)
    beacon = policy.decide(
        "https://static.cloudflareinsights.com/beacon.min.js/v31edd",
        "GET",
    )
    rum = policy.decide(f"{ORIGIN}/cdn-cgi/rum", "POST")
    for decision in (beacon, rum):
        assert decision.allowed is False
        assert decision.category == "edge"


# ---------------------------------------------------------------------------
# R6/R7 — observations without credentials
# ---------------------------------------------------------------------------


def test_sanitize_url_drops_query_and_fragment():
    assert browser.sanitize_url("https://h/p?username=x&password=y#z") == "https://h/p"
    assert browser.sanitize_url("https://h/p") == "https://h/p"


def test_observations_separate_violations_from_expected_and_edge_blocks():
    policy = browser.RequestPolicy(origin=ORIGIN)
    allowed = browser.Observations(policy)
    allowed.decide("https://evil.example/x", "GET")
    assert len(allowed.violations) == 1
    assert allowed.expected_blocks == []
    allowed.decide(f"{ORIGIN}/cdn-cgi/rum", "POST")
    assert len(allowed.edge_blocks) == 1
    assert len(allowed.violations) == 1

    probing = browser.Observations(policy, expect_blocks=True)
    probing.decide(f"{ORIGIN}/ingestao/sincronizar-demograficos/", "GET")
    assert probing.violations == []
    assert len(probing.expected_blocks) == 1


def test_observations_record_js_errors_but_not_resource_load_noise():
    observed = browser.Observations(browser.RequestPolicy(origin=ORIGIN))
    observed.note_console("error", "Uncaught TypeError: x is undefined")
    observed.note_console("error", "Failed to load resource: net::ERR_FAILED")
    observed.note_console("log", "hello")
    observed.note_page_error("boom")
    assert len(observed.js_errors) == 2


def test_observations_redact_credentials_from_every_channel():
    observed = browser.Observations(browser.RequestPolicy(origin=ORIGIN), redactions=("SECRET-VALUE",))
    observed.note_console("error", "token SECRET-VALUE rejected")
    observed.note_page_error("SECRET-VALUE")
    assert all("SECRET-VALUE" not in entry for entry in observed.js_errors)
    assert any("redacted" in entry for entry in observed.js_errors)


def test_observations_flag_unexpected_http_and_ignore_favicon():
    observed = browser.Observations(browser.RequestPolicy(origin=ORIGIN))
    observed.note_response(f"{ORIGIN}/censo/", 200)
    observed.note_response(f"{ORIGIN}/censo/exportar/", 500)
    observed.note_response(f"{ORIGIN}/favicon.ico", 404)
    assert len(observed.http_unexpected) == 1
    assert "censo/exportar/" in observed.http_unexpected[0]
    assert "?x=" not in observed.http_unexpected[0]


def test_observations_track_required_assets_by_prefix():
    observed = browser.Observations(browser.RequestPolicy(origin=ORIGIN))
    observed.note_response(f"{ORIGIN}/static/css/sirhosp.css", 200)
    observed.note_response("https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js", 200)
    observed.note_response(
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css", 200
    )
    assert (
        observed.missing_assets(
            (
                f"{ORIGIN}/static/css/sirhosp.css",
                "https://unpkg.com/htmx.org@2.0.4",
                "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css",
            )
        )
        == []
    )
    missing = observed.missing_assets(browser.REQUIRED_ASSETS)
    assert "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css" in missing


def test_observations_ignore_failures_of_edge_and_blocked_requests():
    policy = browser.RequestPolicy(origin=ORIGIN)
    observed = browser.Observations(policy)
    beacon = "https://static.cloudflareinsights.com/beacon.min.js/v1"
    observed.decide(beacon, "GET")
    observed.note_request_failed(beacon, "net::ERR_FAILED")
    observed.note_request_failed(
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/x", "net::ERR_TIMED_OUT"
    )
    assert len(observed.failed_requests) == 1
    assert "cdn.jsdelivr.net" in observed.failed_requests[0]


# ---------------------------------------------------------------------------
# R6 — queue metadata comparison (never delete jobs)
# ---------------------------------------------------------------------------


def test_queue_metadata_reports_no_change():
    clean, changes = browser.compare_queue_metadata({"ingestion:total": 3}, {"ingestion:total": 3})
    assert clean is True
    assert changes == []


def test_queue_metadata_detects_creation_and_removal():
    clean, changes = browser.compare_queue_metadata(
        {"ingestion:total": 3, "summary:total": 1},
        {"ingestion:total": 5, "summary:total": 1},
    )
    assert clean is False
    assert any("ingestion:total" in change for change in changes)
    clean, changes = browser.compare_queue_metadata(
        {"ingestion:total": 3}, {"ingestion:total": 2}
    )
    assert clean is False
    assert any("ingestion:total" in change for change in changes)


def test_queue_metadata_detects_new_key():
    clean, changes = browser.compare_queue_metadata({}, {"ingestion:queued": 1})
    assert clean is False
    assert changes


# ---------------------------------------------------------------------------
# D7 — aggregation and exit codes
# ---------------------------------------------------------------------------


def _evidence(*statuses, cleanup=browser.PASS, failure="", **overrides):
    evidence = browser.RunEvidence(
        run_id=RUN,
        feature="auth",
        target="dev",
        roles=("user",),
        viewports=("desktop",),
        started_at="2026-10-04T00:00:00+00:00",
    )
    for index, status in enumerate(statuses):
        evidence.cases.append(browser.CaseResult(f"case-{index}", "user", "desktop", status))
    evidence.cleanup = cleanup
    evidence.failure = failure
    for key, value in overrides.items():
        setattr(evidence, key, value)
    return evidence


def test_aggregate_all_pass():
    aggregate = browser.build_aggregate(_evidence(browser.PASS, browser.PASS))
    assert aggregate.status == browser.PASS
    assert aggregate.exit_code == 0
    assert aggregate.counts[browser.PASS] == 2


def test_aggregate_fail_wins_over_blocked_and_skipped():
    aggregate = browser.build_aggregate(_evidence(browser.SKIPPED, browser.BLOCKED, browser.FAIL))
    assert aggregate.status == browser.FAIL
    assert aggregate.exit_code == browser.EXIT_CODES[browser.FAIL]


def test_aggregate_blocked_wins_over_skipped():
    aggregate = browser.build_aggregate(_evidence(browser.SKIPPED, browser.BLOCKED))
    assert aggregate.status == browser.BLOCKED
    assert aggregate.exit_code == 2


def test_aggregate_skipped_only():
    aggregate = browser.build_aggregate(_evidence(browser.SKIPPED))
    assert aggregate.status == browser.SKIPPED
    assert aggregate.exit_code == 3


def test_aggregate_cleanup_failure_forces_nonzero_exit():
    aggregate = browser.build_aggregate(_evidence(browser.PASS, cleanup=browser.FAIL))
    assert aggregate.status == browser.FAIL
    assert aggregate.exit_code == 1
    assert any("cleanup" in reason for reason in aggregate.reasons)


def test_aggregate_run_failure_forces_nonzero_exit():
    aggregate = browser.build_aggregate(_evidence(browser.PASS, failure="AssertionError: injected"))
    assert aggregate.status == browser.FAIL
    assert aggregate.exit_code == 1


@pytest.mark.parametrize(
    "field, value",
    [
        ("request_violations", ["GET /ingestao/criar/"]),
        ("js_errors", ["Uncaught TypeError"]),
        ("http_unexpected", ["/censo/ -> 500"]),
        ("failed_requests", ["https://x/y net::ERR"]),
        ("missing_assets", ["https://cdn/y"]),
        ("queue_changes", ["ingestion:total 1 -> 2"]),
    ],
)
def test_aggregate_global_observations_fail_the_run(field, value):
    aggregate = browser.build_aggregate(_evidence(browser.PASS, **{field: list(value)}))
    assert aggregate.status == browser.FAIL
    assert aggregate.exit_code == 1


def test_aggregate_without_cases_is_blocked_not_pass():
    aggregate = browser.build_aggregate(_evidence())
    assert aggregate.status == browser.BLOCKED
    assert aggregate.exit_code == 2


def test_aggregate_ignores_deliberate_blocks():
    aggregate = browser.build_aggregate(
        _evidence(
            browser.PASS,
            deliberate_blocks=["GET /ingestao/sincronizar-demograficos/ refused"],
        )
    )
    assert aggregate.status == browser.PASS


def test_exit_codes_follow_d7():
    assert browser.EXIT_CODES == {
        browser.PASS: 0,
        browser.FAIL: 1,
        browser.BLOCKED: 2,
        browser.SKIPPED: 3,
    }


# ---------------------------------------------------------------------------
# R7 — evidence writing
# ---------------------------------------------------------------------------


def test_write_evidence_produces_json_and_markdown(tmp_path):
    evidence = _evidence(browser.PASS, browser.BLOCKED)
    evidence.cases.append(
        browser.CaseResult(
            "census-filter-positive", "user", "desktop", browser.BLOCKED, "no descriptor"
        )
    )
    evidence.screenshots.append("screenshots/login.png")
    evidence.queue_changes = []
    path = browser.write_evidence(tmp_path, evidence)
    payload = json.loads(Path(path).read_text())
    assert payload["run_id"] == RUN
    assert payload["feature"] == "auth"
    assert len(payload["cases"]) == 3
    assert payload["cleanup"] == browser.PASS
    assert (tmp_path / "summary.md").is_file()
    assert "census-filter-positive" in (tmp_path / "summary.md").read_text()


def test_write_evidence_never_contains_credentials(tmp_path):
    evidence = _evidence(browser.PASS)
    evidence.cases.append(
        browser.CaseResult("auth-login", "user", "desktop", browser.PASS, "ok", ("«redacted»",))
    )
    evidence.failure = "cleanup failed"
    path = browser.write_evidence(tmp_path, evidence)
    raw = Path(path).read_text()
    for forbidden in (
        "verify_user",
        "verify_admin",
        "password",
        "csrf",
        "cookie",
        "authorization",
        "set-cookie",
    ):
        assert forbidden not in raw.lower()


# ---------------------------------------------------------------------------
# R3 — expectations and honest BLOCKED
# ---------------------------------------------------------------------------


def test_load_expectations_without_path_is_not_ready():
    expectations = browser.load_expectations(None)
    assert expectations.census_filter is None
    assert expectations.reason == "expectations not provided"


def test_load_expectations_missing_file_is_not_ready(tmp_path):
    expectations = browser.load_expectations(str(tmp_path / "absent.json"))
    assert expectations.census_filter is None
    assert expectations.reason.startswith("expectations unreadable")


def test_load_expectations_invalid_payload_is_not_ready(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    assert browser.load_expectations(str(path)).census_filter is None
    path.write_text(json.dumps({"census_filter": {"query": "nope"}}))
    expectations = browser.load_expectations(str(path))
    assert expectations.census_filter is None
    assert expectations.reason.startswith("expectations invalid")


def test_load_expectations_valid_payload(tmp_path):
    path = tmp_path / "ok.json"
    path.write_text(
        json.dumps(
            {
                "census_filter": {
                    "query": {"q": "FICTICIO", "unidade": "SETOR TESTE"},
                    "expect_registro": "0000001",
                    "expect_nome": "PACIENTE FICTICIO",
                    "expect_rows": 1,
                }
            }
        )
    )
    expectations = browser.load_expectations(str(path))
    assert expectations.census_filter is not None
    assert expectations.census_filter.query["unidade"] == "SETOR TESTE"
    assert expectations.census_filter.expect_rows == 1


def test_census_filter_positive_is_blocked_without_expectations():
    ctx = _journey_context(expectations=browser.Expectations())
    outcome = browser.case_census_filter_positive(ctx)
    assert outcome.status == browser.BLOCKED
    assert outcome.detail


def test_census_filter_positive_never_passes_on_invalid_expectations():
    ctx = _journey_context(
        expectations=browser.Expectations(reason="expectations invalid: missing")
    )
    outcome = browser.case_census_filter_positive(ctx)
    assert outcome.status == browser.BLOCKED
    assert outcome.status != browser.PASS


# ---------------------------------------------------------------------------
# R4 — case plan per feature and viewport
# ---------------------------------------------------------------------------


def _plan_ids(feature, viewport):
    return [case_id for case_id, _ in browser.case_plan(feature, viewport)]


def test_case_plan_auth_covers_login_shell_visibility_logout():
    ids = _plan_ids("auth", browser.DESKTOP)
    assert "auth-login" in ids
    assert "auth-shell" in ids
    assert "auth-visibility" in ids
    assert "auth-logout" in ids
    assert "topbar-polls" not in ids
    assert "census-tomselect" not in ids


def test_case_plan_smoke_desktop_polls_and_mobile_uses_menu():
    desktop = _plan_ids("smoke", browser.DESKTOP)
    mobile = _plan_ids("smoke", browser.MOBILE)
    assert "census-tomselect" in desktop and "census-tomselect" in mobile
    assert "census-filter-positive" in desktop
    assert "topbar-polls" in desktop
    assert "mobile-nav" not in desktop
    assert "mobile-nav" in mobile
    assert "topbar-polls" not in mobile
    assert "auth-logout" in mobile


# ---------------------------------------------------------------------------
# R1/R8 — driver orchestration, cleanup and injected controlled failures
# ---------------------------------------------------------------------------


class FakePage:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeContextHandle:
    def __init__(self, page):
        self.page = page
        self.closed = False
        self.observations = None

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, close_error=None):
        self.contexts = []
        self.closed = False
        self.close_error = close_error

    def new_role_context(self, *, role, viewport, observations):
        handle = FakeContextHandle(FakePage())
        handle.observations = observations
        self.contexts.append((role, viewport.name, handle))
        return handle

    def close(self):
        self.closed = True
        if self.close_error is not None:
            raise RuntimeError(self.close_error)


def _journey_context(expectations=None, observations=None, role="user", viewport=None):
    return browser.JourneyContext(
        role=role,
        viewport=viewport or browser.DESKTOP,
        page=FakePage(),
        context=None,
        observations=observations or browser.Observations(browser.RequestPolicy(origin=ORIGIN)),
        expectations=expectations or browser.Expectations(),
        base_url=ORIGIN,
        evidence=browser.RunEvidence(
            run_id=RUN,
            feature="auth",
            target="dev",
            roles=(role,),
            viewports=("desktop",),
            started_at="2026-10-04T00:00:00+00:00",
        ),
        evidence_dir=Path("/tmp/does-not-matter"),
        timeout_ms=1000,
    )


def _runner(status=browser.PASS, detail="ok", hook=None):
    def run(ctx):
        if hook is not None:
            hook(ctx)
        return browser.CaseOutcome(status, detail)

    return run


def _driver(session, tmp_path, cases, *, policy_cases=None, queue_probe=None, expectations=None):
    return browser.SmokeDriver(
        session=session,
        evidence_dir=tmp_path / "evidence",
        base_url=ORIGIN,
        expectations=expectations,
        case_table=lambda feature, viewport: cases,
        policy_case_table=lambda feature, viewport: policy_cases or (),
        queue_probe=queue_probe,
    )


def _evidence_for(driver, *, roles=("user",), viewports=None, inject_failure=None):
    evidence = browser.RunEvidence(
        run_id=RUN,
        feature="auth",
        target="dev",
        roles=tuple(roles),
        viewports=tuple(v.name for v in (viewports or (browser.DESKTOP,))),
        started_at="2026-10-04T00:00:00+00:00",
    )
    evidence.cleanup = browser.PASS
    driver.execute(
        evidence,
        feature="auth",
        roles=roles,
        viewports=viewports or (browser.DESKTOP,),
        inject_failure=inject_failure,
    )
    return evidence


def test_driver_uses_one_fresh_context_per_role_and_viewport(tmp_path):
    session = FakeSession()
    driver = _driver(session, tmp_path, (("case-a", _runner()),))
    _evidence_for(driver, roles=("user", "admin"), viewports=(browser.DESKTOP, browser.MOBILE))
    observed = [(role, name) for role, name, _ in session.contexts]
    assert observed == [
        ("user", "desktop"),
        ("user", "mobile"),
        ("admin", "desktop"),
        ("admin", "mobile"),
        ("both", "desktop"),
    ]


def test_driver_closes_every_context_and_collects_observations(tmp_path):
    session = FakeSession()

    def hook(ctx):
        ctx.observations.note_console("error", "Uncaught boom")
        ctx.observations.decide("https://evil.example/x", "GET")

    driver = _driver(session, tmp_path, (("case-a", _runner(hook=hook)),))
    evidence = _evidence_for(driver)
    assert all(handle.closed for _, _, handle in session.contexts)
    assert len(evidence.cases) == 1
    assert evidence.js_errors == ["Uncaught boom"]
    assert len(evidence.request_violations) == 1


def test_driver_records_assertion_failure_and_keeps_running(tmp_path):
    session = FakeSession()

    def boom(ctx):
        raise AssertionError("panel did not render identity")

    driver = _driver(session, tmp_path, (("case-a", _runner(hook=boom)), ("case-b", _runner())))
    evidence = _evidence_for(driver)
    assert [case.status for case in evidence.cases] == [browser.FAIL, browser.PASS]
    assert "panel did not render identity" in evidence.cases[0].detail
    aggregate = browser.build_aggregate(evidence)
    assert aggregate.status == browser.FAIL
    assert aggregate.exit_code == 1


def test_driver_maps_timeout_to_fail_not_pass(tmp_path):
    session = FakeSession()

    def slow(ctx):
        raise browser.DriverTimeout("waiting for #id_username")

    driver = _driver(session, tmp_path, (("case-a", _runner(hook=slow)),))
    evidence = _evidence_for(driver)
    assert evidence.cases[0].status == browser.FAIL
    assert "timeout" in evidence.cases[0].detail
    assert browser.build_aggregate(evidence).exit_code == 1


def test_driver_maps_missing_prerequisite_to_blocked(tmp_path):
    session = FakeSession()

    def blocked(ctx):
        raise browser.DriverBlocked("no unit options")

    driver = _driver(session, tmp_path, (("case-a", _runner(hook=blocked)),))
    evidence = _evidence_for(driver)
    assert evidence.cases[0].status == browser.BLOCKED
    assert browser.build_aggregate(evidence).exit_code == 2


def test_driver_injected_assertion_escapes_after_contexts_closed(tmp_path):
    session = FakeSession()
    driver = _driver(session, tmp_path, (("case-a", _runner()),))
    with pytest.raises(AssertionError):
        _evidence_for(driver, inject_failure="assert")
    assert all(handle.closed for _, _, handle in session.contexts)


def test_driver_injected_timeout_escapes_after_contexts_closed(tmp_path):
    session = FakeSession()
    driver = _driver(session, tmp_path, (("case-a", _runner()),))
    with pytest.raises(browser.DriverTimeout):
        _evidence_for(driver, inject_failure="timeout")
    assert all(handle.closed for _, _, handle in session.contexts)


def test_driver_policy_context_treats_blocks_as_expected(tmp_path):
    session = FakeSession()

    def probing(ctx):
        assert ctx.observations.expect_blocks is True
        ctx.observations.decide(f"{ORIGIN}/ingestao/sincronizar-demograficos/", "GET")
        return browser.CaseOutcome(browser.PASS, "blocked before effect")

    driver = _driver(
        session, tmp_path, (("case-a", _runner()),), policy_cases=(("policy", probing),)
    )
    evidence = _evidence_for(driver)
    assert evidence.request_violations == []
    assert len(evidence.deliberate_blocks) == 1
    assert browser.build_aggregate(evidence).status == browser.PASS


def test_driver_queue_probe_detects_new_jobs(tmp_path):
    session = FakeSession()
    probes = iter([{"ingestion:total": 1}, {"ingestion:total": 2}])
    driver = _driver(session, tmp_path, (("case-a", _runner()),), queue_probe=lambda: next(probes))
    evidence = _evidence_for(driver)
    assert evidence.queue_changes
    assert browser.build_aggregate(evidence).status == browser.FAIL


def test_driver_queue_probe_error_is_a_fail_case(tmp_path):
    session = FakeSession()

    def broken():
        raise RuntimeError("docker exec unavailable")

    driver = _driver(session, tmp_path, (("case-a", _runner()),), queue_probe=broken)
    evidence = _evidence_for(driver)
    queue_cases = [case for case in evidence.cases if case.case == "queue-metadata"]
    assert len(queue_cases) == 1
    assert queue_cases[0].status == browser.FAIL


def test_close_browser_reports_failure_without_raising(tmp_path):
    session = FakeSession(close_error="browser already gone")
    driver = _driver(session, tmp_path, (("case-a", _runner()),))
    error = driver.close_browser()
    assert error is not None and "browser already gone" in error
    assert _driver(FakeSession(), tmp_path, (("case-a", _runner()),)).close_browser() is None


# ---------------------------------------------------------------------------
# CLI — run command, cleanup ordering and exit codes
# ---------------------------------------------------------------------------


class _PassRunner:
    """A case runner that only proves the orchestration path."""

    def __init__(self, browser_module):
        self.browser = browser_module

    def __call__(self, ctx):
        return self.browser.CaseOutcome(self.browser.PASS, "ok")


class _LeakyRunner:
    """A case runner that leaks a credential into a console channel."""

    def __init__(self, browser_module):
        self.browser = browser_module

    def __call__(self, ctx):
        ctx.observations.note_page_error("leak SECRET-USER")
        return self.browser.CaseOutcome(self.browser.PASS, "ok")


def _target():
    return SimpleNamespace(
        slug="dev",
        fingerprint="d" * 64,
        web_running=True,
        db_address="172.18.0.2",
        db_port=5432,
        docker_host="unix:///run/user/1003/docker.sock",
        checkout="/projects/dev/sirhosp",
        volume="sirhosp_sirhosp_db_data",
        compose=["docker", "compose"],
    )


def _patch_run(
    monkeypatch, controller, tmp_path, *, close_status="PASS", browser_close_error=None, runner=None
):
    monkeypatch.setattr(browser, "EVIDENCE_ROOT", tmp_path / "evidence")
    monkeypatch.setattr(controller, "_resolve_target", lambda name: _target())
    monkeypatch.setattr(
        controller,
        "cmd_open",
        lambda *args, **kwargs: controller.OpenCredentials(
            run_id=RUN,
            passwords={"verify_user": "SECRET-USER", "verify_admin": "SECRET-ADMIN"},
            origin=ORIGIN,
        ),
    )
    monkeypatch.setattr(
        controller, "_collect_db_identity", lambda *a, **k: ("d" * 64, "172.18.0.2", 5432)
    )
    monkeypatch.setattr(controller, "_queue_metadata", lambda *a, **k: {"ingestion:total": 1})
    monkeypatch.setattr(
        controller,
        "cmd_close",
        lambda *args, **kwargs: controller.Verdict(status=close_status, revoked=True),
    )
    captured = {}
    case_runner = runner or _PassRunner(browser)

    def factory(*, evidence_dir, redactions, expectations, queue_probe, credentials, origin):
        captured["evidence_dir"] = evidence_dir
        captured["redactions"] = redactions
        captured["credentials"] = credentials
        captured["origin"] = origin
        session = FakeSession(close_error=browser_close_error)
        captured["session"] = session
        driver = browser.SmokeDriver(
            session=session,
            evidence_dir=evidence_dir,
            base_url=origin,
            expectations=expectations,
            credentials=credentials,
            redactions=redactions,
            case_table=lambda feature, viewport: (("case-a", case_runner),),
            policy_case_table=lambda feature, viewport: (),
            queue_probe=queue_probe,
        )
        captured["driver"] = driver
        return driver

    captured["factory"] = factory
    return captured


def test_cmd_run_requires_synthetic_confirmation(controller, monkeypatch, tmp_path):
    monkeypatch.setattr(controller, "_resolve_target", lambda name: _target())
    opened = []
    monkeypatch.setattr(controller, "cmd_open", lambda *a, **k: opened.append(1))
    with pytest.raises(controller.Blocked):
        controller.cmd_run(
            "dev", feature="auth", roles=("user",), confirm_synthetic_data=False
        )
    assert opened == []


def test_cmd_run_closes_session_and_browser_and_writes_evidence(controller, monkeypatch, tmp_path):
    captured = _patch_run(monkeypatch, controller, tmp_path)
    outcome = controller.cmd_run(
        "dev",
        feature="auth",
        roles=("user",),
        confirm_synthetic_data=True,
        viewport_names=("desktop",),
        driver_factory=captured["factory"],
    )
    assert outcome.exit_code == 0
    assert outcome.status == browser.PASS
    assert outcome.cleanup == browser.PASS
    assert captured["session"].closed is True
    assert captured["redactions"] == ("SECRET-USER", "SECRET-ADMIN")
    assert captured["credentials"] == {
        "verify_user": "SECRET-USER",
        "verify_admin": "SECRET-ADMIN",
    }
    report = Path(outcome.evidence_dir) / "report.json"
    assert report.is_file()
    assert "SECRET-USER" not in report.read_text()
    assert RUN in str(outcome.evidence_dir)


def test_cmd_run_sanitizes_credentials_in_evidence(controller, monkeypatch, tmp_path):
    captured = _patch_run(monkeypatch, controller, tmp_path, runner=_LeakyRunner(browser))
    outcome = controller.cmd_run(
        "dev",
        feature="auth",
        roles=("user",),
        confirm_synthetic_data=True,
        viewport_names=("desktop",),
        driver_factory=captured["factory"],
    )
    raw = (Path(outcome.evidence_dir) / "report.json").read_text()
    assert "SECRET-USER" not in raw
    assert "redacted" in raw
    assert outcome.exit_code == 1


def test_cmd_run_reports_cleanup_failure_with_nonzero_exit(controller, monkeypatch, tmp_path):
    captured = _patch_run(monkeypatch, controller, tmp_path, close_status="FAIL")
    outcome = controller.cmd_run(
        "dev",
        feature="auth",
        roles=("user",),
        confirm_synthetic_data=True,
        viewport_names=("desktop",),
        driver_factory=captured["factory"],
    )
    assert outcome.cleanup == browser.FAIL
    assert outcome.exit_code == 1
    assert captured["session"].closed is True
    report = json.loads((Path(outcome.evidence_dir) / "report.json").read_text())
    assert report["cleanup"] == browser.FAIL


def test_cmd_run_reports_browser_close_failure_with_nonzero_exit(controller, monkeypatch, tmp_path):
    captured = _patch_run(monkeypatch, controller, tmp_path, browser_close_error="browser gone")
    outcome = controller.cmd_run(
        "dev",
        feature="auth",
        roles=("user",),
        confirm_synthetic_data=True,
        viewport_names=("desktop",),
        driver_factory=captured["factory"],
    )
    assert outcome.cleanup == browser.FAIL
    assert outcome.exit_code == 1


def test_cmd_run_keeps_evidence_after_injected_failure(controller, monkeypatch, tmp_path):
    captured = _patch_run(monkeypatch, controller, tmp_path)
    closed = []
    monkeypatch.setattr(
        controller,
        "cmd_close",
        lambda *a, **k: closed.append(k) or controller.Verdict("PASS", True),
    )
    outcome = controller.cmd_run(
        "dev",
        feature="auth",
        roles=("user",),
        confirm_synthetic_data=True,
        viewport_names=("desktop",),
        inject_failure="assert",
        driver_factory=captured["factory"],
    )
    assert outcome.exit_code == 1
    assert closed
    assert captured["session"].closed is True
    assert outcome.cases  # completed cases are preserved in the evidence


def test_cmd_run_rejects_unknown_feature(controller, monkeypatch):
    monkeypatch.setattr(controller, "_resolve_target", lambda name: _target())
    monkeypatch.setattr(
        controller, "_collect_db_identity", lambda *a, **k: ("d" * 64, "172.18.0.2", 5432)
    )
    with pytest.raises(controller.Blocked):
        controller.cmd_run(
            "dev", feature="everything", roles=("user",), confirm_synthetic_data=True
        )


def test_cmd_run_rejects_unknown_role(controller, monkeypatch):
    monkeypatch.setattr(controller, "_resolve_target", lambda name: _target())
    with pytest.raises(controller.Blocked):
        controller.cmd_run(
            "dev", feature="auth", roles=("root",), confirm_synthetic_data=True
        )


# ---------------------------------------------------------------------------
# R6 — queue metadata probe
# ---------------------------------------------------------------------------


def test_queue_metadata_parses_counts(controller, monkeypatch):
    monkeypatch.setattr(controller, "_validate_runtime", lambda target: None)
    monkeypatch.setattr(controller, "_command", lambda *a, **k: '{"ingestion:total": 4}')
    assert controller._queue_metadata(_target()) == {"ingestion:total": 4}


def test_queue_metadata_rejects_invalid_output(controller, monkeypatch):
    monkeypatch.setattr(controller, "_validate_runtime", lambda target: None)
    monkeypatch.setattr(controller, "_command", lambda *a, **k: "not json")
    with pytest.raises(controller.Failure):
        controller._queue_metadata(_target())


# ---------------------------------------------------------------------------
# Repair v3 — hop prevention, popup/WS/SW boundaries, in-memory sanitization
# ---------------------------------------------------------------------------


class _FakeCDPSession:
    """Records the CDP traffic of the per-page hop layer."""

    def __init__(self, *, fail: tuple[str, ...] = (), on_detach: Any = None) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.handlers: dict[str, Any] = {}
        self._fail = fail
        # Requests Chromium paused but neither continued nor failed yet. A
        # successful ``send`` resolves its own request; ``detach`` resolves
        # every paused request with ERR_ABORTED, like the real session.
        self.pending: list[str] = []
        self.detached = False
        self.detach_calls = 0
        # Test hook: observe the run state at the moment detach is attempted.
        self.on_detach = on_detach

    def pause(self, request_id: str) -> None:
        self.pending.append(request_id)

    def send(self, method: str, params: dict | None = None) -> None:
        if method in self._fail:
            raise RuntimeError(f"{method} refused by the fake session")
        self.sent.append((method, params or {}))
        request_id = (params or {}).get("requestId")
        if request_id in self.pending:
            self.pending.remove(request_id)

    def detach(self) -> None:
        if self.on_detach is not None:
            self.on_detach()
        self.detach_calls += 1
        self.detached = True
        self.pending.clear()

    def on(self, event: str, handler: Any) -> None:
        self.handlers[event] = handler


class _FakeObservedPage:
    def __init__(self, url: str = "about:blank") -> None:
        self.url = url
        self.handlers: dict[str, Any] = {}

    def on(self, event: str, handler: Any) -> None:
        self.handlers[event] = handler


class _FakeOwnedContext:
    def __init__(self, cdp: _FakeCDPSession, *, close_error: str | None = None) -> None:
        self.cdp = cdp
        self.page = _FakeObservedPage()
        self.init_scripts: list[str] = []
        self.route_pattern: str | None = None
        self.route_handler: Any = None
        self.websocket_pattern: str | None = None
        self.websocket_handler: Any = None
        self.handlers: dict[str, Any] = {}
        self.default_timeout: float | None = None
        self.closed = False
        self.close_calls = 0
        self.close_error = close_error
        # Test hook: observe the run state at the moment close is attempted.
        self.on_close: Any = None

    def set_default_timeout(self, timeout: float) -> None:
        self.default_timeout = timeout

    def add_init_script(self, script: str | None = None, path: Any = None) -> None:
        self.init_scripts.append(script or "")

    def route(self, pattern: str, handler: Any) -> None:
        self.route_pattern = pattern
        self.route_handler = handler

    def route_web_socket(self, pattern: str, handler: Any) -> None:
        self.websocket_pattern = pattern
        self.websocket_handler = handler

    def new_page(self) -> _FakeObservedPage:
        return self.page

    def new_cdp_session(self, page: Any) -> _FakeCDPSession:
        return self.cdp

    def on(self, event: str, handler: Any) -> None:
        self.handlers[event] = handler

    def close(self) -> None:
        if self.on_close is not None:
            self.on_close()
        self.close_calls += 1
        if self.close_error is not None:
            raise RuntimeError(self.close_error)
        self.closed = True
        # Closing the owned context detaches its CDP session, which resolves
        # every paused request, like the real Chromium teardown.
        self.cdp.pending.clear()


class _FakeLaunchBrowser:
    """A fake Chromium so the real driver class runs without a browser."""

    def __init__(self, cdp: _FakeCDPSession | None = None) -> None:
        self.cdp = cdp or _FakeCDPSession()
        self.context = _FakeOwnedContext(self.cdp)
        self.new_context_kwargs: dict[str, Any] = {}
        self.new_context_calls = 0
        self.closed = False
        self.close_calls = 0

    def new_context(self, **kwargs: Any) -> _FakeOwnedContext:
        self.new_context_calls += 1
        self.new_context_kwargs = kwargs
        return self.context

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _FakeRoute:
    def __init__(self, url: str, *, method: str = "GET", page: Any = None) -> None:
        self.request = SimpleNamespace(
            url=url, method=method, frame=SimpleNamespace(page=page)
        )
        self.actions: list[str] = []

    def continue_(self) -> None:
        self.actions.append("continue")

    def abort(self) -> None:
        self.actions.append("abort")


def _owned_context(
    observations: browser.Observations | None = None, cdp: _FakeCDPSession | None = None
) -> tuple[_FakeLaunchBrowser, browser._RoleContext]:
    session = browser.PlaywrightBrowser(base_url=ORIGIN)
    fake = _FakeLaunchBrowser(cdp)
    session._browser = fake
    handle = session.new_role_context(
        role="user",
        viewport=browser.DESKTOP,
        observations=observations or browser.Observations(browser.RequestPolicy(origin=ORIGIN)),
    )
    return fake, handle


def test_owned_context_blocks_service_workers():
    fake, _ = _owned_context()
    assert fake.new_context_kwargs["service_workers"] == "block"


def test_owned_context_installs_the_popup_guard_script():
    fake, _ = _owned_context()
    assert len(fake.context.init_scripts) == 1
    script = fake.context.init_scripts[0]
    assert browser.POPUP_BLOCK_MARKER in script
    assert "window.open" in script
    assert "[target=_blank]" in script


def test_owned_context_attaches_the_cdp_hop_layer():
    fake, _ = _owned_context()
    assert (
        "Fetch.enable",
        {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]},
    ) in fake.cdp.sent
    assert "Fetch.requestPaused" in fake.cdp.handlers


def test_cdp_layer_refuses_a_hop_outside_the_policy():
    observations = browser.Observations(browser.RequestPolicy(origin=ORIGIN))
    fake, _ = _owned_context(observations)
    fake.cdp.handlers["Fetch.requestPaused"](
        {"requestId": "7", "request": {"url": "https://evil.example/steal", "method": "GET"}}
    )
    assert (
        "Fetch.failRequest",
        {"requestId": "7", "errorReason": "Aborted"},
    ) in fake.cdp.sent
    assert len(observations.violations) == 1
    assert "evil.example" in observations.violations[0]


def test_cdp_layer_continues_an_allowed_request_without_a_violation():
    observations = browser.Observations(browser.RequestPolicy(origin=ORIGIN))
    fake, _ = _owned_context(observations)
    fake.cdp.handlers["Fetch.requestPaused"](
        {"requestId": "8", "request": {"url": f"{ORIGIN}/painel/", "method": "GET"}}
    )
    assert ("Fetch.continueRequest", {"requestId": "8"}) in fake.cdp.sent
    assert observations.violations == []


def test_cdp_layer_records_a_failed_fail_request_as_a_violation():
    observations = browser.Observations(browser.RequestPolicy(origin=ORIGIN))
    fake, _ = _owned_context(observations, _FakeCDPSession(fail=("Fetch.failRequest",)))
    fake.cdp.handlers["Fetch.requestPaused"](
        {"requestId": "9", "request": {"url": "https://evil.example/steal", "method": "GET"}}
    )
    assert len(observations.violations) == 2
    assert "host outside the allowlist" in observations.violations[0]
    assert "Fetch.failRequest" in observations.violations[1]


def test_cdp_layer_records_a_failed_continue_request_and_releases_the_page():
    observations = browser.Observations(browser.RequestPolicy(origin=ORIGIN))
    fake, _ = _owned_context(observations, _FakeCDPSession(fail=("Fetch.continueRequest",)))
    fake.cdp.handlers["Fetch.requestPaused"](
        {"requestId": "10", "request": {"url": f"{ORIGIN}/painel/", "method": "GET"}}
    )
    assert len(observations.violations) == 1
    assert "Fetch.continueRequest" in observations.violations[0]
    assert fake.context.closed is True
    assert ("Fetch.continueRequest", {"requestId": "10"}) not in fake.cdp.sent


def test_cdp_layer_releases_the_page_when_fail_request_cannot_be_sent():
    observations = browser.Observations(browser.RequestPolicy(origin=ORIGIN))
    fake, _ = _owned_context(observations, _FakeCDPSession(fail=("Fetch.failRequest",)))
    fake.cdp.handlers["Fetch.requestPaused"](
        {"requestId": "11", "request": {"url": "https://evil.example/steal", "method": "GET"}}
    )
    assert len(observations.violations) == 2
    assert "Fetch.failRequest" in observations.violations[1]
    assert fake.context.closed is True
    assert ("Fetch.failRequest", {"requestId": "11", "errorReason": "Aborted"}) not in (
        fake.cdp.sent
    )


def test_cdp_release_failure_is_visible_and_resolves_the_paused_request():
    observations = browser.Observations(browser.RequestPolicy(origin=ORIGIN))
    cdp = _FakeCDPSession(fail=("Fetch.failRequest",))
    cdp.pause("12")
    fake, _ = _owned_context(observations, cdp)
    fake.context.close_error = "context already closing"
    fake.cdp.handlers["Fetch.requestPaused"](
        {"requestId": "12", "request": {"url": "https://evil.example/steal", "method": "GET"}}
    )
    assert "host outside the allowlist" in observations.violations[0]
    assert "Fetch.failRequest" in observations.violations[1]
    assert any("cdp release failed" in entry for entry in observations.violations)
    assert observations.fatal is True
    assert fake.cdp.pending == []
    assert fake.cdp.detach_calls >= 1
    assert browser.build_aggregate(_evidence_with(observations)).status == browser.FAIL


def test_cdp_action_failure_marks_fatal_even_when_release_succeeds():
    observations = browser.Observations(browser.RequestPolicy(origin=ORIGIN))
    cdp = _FakeCDPSession(fail=("Fetch.failRequest",))
    cdp.pause("13")
    fake, _ = _owned_context(observations, cdp)
    fake.cdp.handlers["Fetch.requestPaused"](
        {"requestId": "13", "request": {"url": "https://evil.example/steal", "method": "GET"}}
    )
    assert len(observations.violations) == 2
    assert "Fetch.failRequest" in observations.violations[1]
    assert all("cdp release failed" not in entry for entry in observations.violations)
    # The failed CDP action is fatal on its own: the run must not continue even
    # though the best-effort release below closed the owned context cleanly.
    assert observations.fatal is True
    assert fake.cdp.pending == []
    assert fake.context.closed is True


def test_cdp_action_failure_flags_fatal_before_any_release_attempt():
    observations = browser.Observations(browser.RequestPolicy(origin=ORIGIN))
    seen: dict[str, bool] = {}
    cdp = _FakeCDPSession(
        fail=("Fetch.continueRequest",),
        on_detach=lambda: seen.__setitem__("fatal_at_detach", observations.fatal),
    )
    fake, _ = _owned_context(observations, cdp)
    fake.context.on_close = lambda: seen.__setitem__("fatal_at_close", observations.fatal)
    fake.cdp.handlers["Fetch.requestPaused"](
        {"requestId": "14", "request": {"url": f"{ORIGIN}/painel/", "method": "GET"}}
    )
    # Fatal is signalled synchronously, before detach/close can suspend and let
    # the next case start.
    assert seen == {"fatal_at_detach": True, "fatal_at_close": True}
    assert observations.fatal is True


def _evidence_with(observations: browser.Observations) -> browser.RunEvidence:
    evidence = browser.RunEvidence(
        run_id=RUN,
        feature="auth",
        target="dev",
        roles=("user",),
        viewports=("desktop",),
        started_at="2026-10-04T00:00:00+00:00",
    )
    evidence.request_violations.extend(observations.violations)
    return evidence


def test_driver_aborts_remaining_journeys_when_the_release_fails(tmp_path):
    cdp = _FakeCDPSession(fail=("Fetch.failRequest",))
    launch = _FakeLaunchBrowser(cdp)
    launch.context.close_error = "context already closing"
    session = browser.PlaywrightBrowser(base_url=ORIGIN)
    session._browser = launch
    executed: list[str] = []

    def trigger(ctx):
        cdp.pause("21")
        cdp.handlers["Fetch.requestPaused"](
            {
                "requestId": "21",
                "request": {"url": "https://evil.example/steal", "method": "GET"},
            }
        )
        executed.append("case-trigger")
        return browser.CaseOutcome(browser.PASS, "triggered")

    def witness(ctx):
        executed.append("case-witness")
        return browser.CaseOutcome(browser.PASS, "should not run")

    driver = browser.SmokeDriver(
        session=session,
        evidence_dir=tmp_path / "evidence",
        base_url=ORIGIN,
        case_table=lambda feature, viewport: (("case-trigger", trigger), ("case-witness", witness)),
        policy_case_table=lambda feature, viewport: (),
    )
    evidence = browser.RunEvidence(
        run_id=RUN,
        feature="auth",
        target="dev",
        roles=("user", "admin"),
        viewports=("desktop",),
        started_at="2026-10-04T00:00:00+00:00",
    )
    try:
        driver.execute(
            evidence, feature="auth", roles=("user", "admin"), viewports=(browser.DESKTOP,)
        )
    finally:
        close_error = driver.close_browser()
    assert close_error is None
    assert launch.closed is True
    assert executed == ["case-trigger"]
    assert launch.new_context_calls == 1
    assert cdp.pending == []
    assert any("Fetch.failRequest" in entry for entry in evidence.request_violations)
    assert any("cdp release failed" in entry for entry in evidence.request_violations)
    assert browser.build_aggregate(evidence).status == browser.FAIL


def test_driver_aborts_remaining_journeys_after_a_cdp_action_failure(tmp_path):
    # Same as the release-failure case, but the best-effort release SUCCEEDS:
    # the failed CDP action alone must stop the run and fail it.
    cdp = _FakeCDPSession(fail=("Fetch.continueRequest",))
    launch = _FakeLaunchBrowser(cdp)
    session = browser.PlaywrightBrowser(base_url=ORIGIN)
    session._browser = launch
    executed: list[str] = []

    def trigger(ctx):
        cdp.pause("31")
        cdp.handlers["Fetch.requestPaused"](
            {
                "requestId": "31",
                "request": {"url": f"{ORIGIN}/painel/", "method": "GET"},
            }
        )
        executed.append("case-trigger")
        return browser.CaseOutcome(browser.PASS, "triggered")

    def witness(ctx):
        executed.append("case-witness")
        return browser.CaseOutcome(browser.PASS, "should not run")

    driver = browser.SmokeDriver(
        session=session,
        evidence_dir=tmp_path / "evidence",
        base_url=ORIGIN,
        case_table=lambda feature, viewport: (("case-trigger", trigger), ("case-witness", witness)),
        policy_case_table=lambda feature, viewport: (),
    )
    evidence = browser.RunEvidence(
        run_id=RUN,
        feature="auth",
        target="dev",
        roles=("user", "admin"),
        viewports=("desktop",),
        started_at="2026-10-04T00:00:00+00:00",
    )
    try:
        driver.execute(
            evidence, feature="auth", roles=("user", "admin"), viewports=(browser.DESKTOP,)
        )
    finally:
        close_error = driver.close_browser()
    assert close_error is None
    assert executed == ["case-trigger"]
    assert launch.new_context_calls == 1
    assert cdp.pending == []
    assert any("Fetch.continueRequest" in entry for entry in evidence.request_violations)
    assert all("cdp release failed" not in entry for entry in evidence.request_violations)
    assert browser.build_aggregate(evidence).status == browser.FAIL


def test_owned_context_keeps_the_context_route_as_a_second_layer():
    fake, _ = _owned_context()
    assert fake.context.route_pattern == "**/*"
    assert fake.context.route_handler is not None


def test_context_route_defers_recording_to_the_cdp_layer_on_owned_pages():
    observations = browser.Observations(browser.RequestPolicy(origin=ORIGIN))
    fake, handle = _owned_context(observations)
    owned = _FakeRoute("https://evil.example/one", page=handle.page)
    fake.context.route_handler(owned)
    assert owned.actions == ["abort"]
    assert observations.violations == []
    popup = _FakeRoute("https://evil.example/two", page=_FakeObservedPage())
    fake.context.route_handler(popup)
    assert popup.actions == ["abort"]
    assert len(observations.violations) == 1


def test_context_route_still_continues_allowed_requests():
    observations = browser.Observations(browser.RequestPolicy(origin=ORIGIN))
    fake, handle = _owned_context(observations)
    allowed = _FakeRoute(f"{ORIGIN}/painel/", page=handle.page)
    fake.context.route_handler(allowed)
    assert allowed.actions == ["continue"]
    assert observations.violations == []


def test_owned_context_blocks_websockets_with_a_passive_handler():
    observations = browser.Observations(browser.RequestPolicy(origin=ORIGIN))
    fake, _ = _owned_context(observations)
    assert fake.context.websocket_pattern == "**/*"

    class _WebSocketRoute:
        url = "ws://evil.example/socket?token=SECRET"

        def connect_to_server(self) -> None:
            raise AssertionError("the handler must never connect to the server")

        def close(self) -> None:
            raise AssertionError("the handler must stay passive")

    fake.context.websocket_handler(_WebSocketRoute())
    assert len(observations.websocket_blocks) == 1
    assert "evil.example" in observations.websocket_blocks[0]
    assert "token" not in observations.websocket_blocks[0]


def test_popup_guard_marker_from_the_console_is_a_violation():
    observations = browser.Observations(browser.RequestPolicy(origin=ORIGIN))
    observations.note_console(
        "error", f"{browser.POPUP_BLOCK_MARKER} open http://evil.example/steal?token=SECRET"
    )
    assert len(observations.popup_blocks) == 1
    assert observations.js_errors == []
    assert "open" in observations.popup_blocks[0]
    assert "token" not in observations.popup_blocks[0]


def test_unforeseen_popup_page_is_recorded_as_a_violation():
    observations = browser.Observations(browser.RequestPolicy(origin=ORIGIN))
    fake, _ = _owned_context(observations)
    popup = _FakeObservedPage()
    fake.context.handlers["page"](popup)
    assert len(observations.popup_blocks) == 1
    assert "popup" in observations.popup_blocks[0]


def test_driver_merges_popup_and_websocket_blocks_into_the_run_violations(tmp_path):
    session = FakeSession()

    def hook(ctx):
        ctx.observations.note_popup_page("about:blank")
        ctx.observations.note_websocket_attempt("ws://evil.example/socket")

    driver = _driver(session, tmp_path, (("case-a", _runner(hook=hook)),))
    evidence = _evidence_for(driver)
    assert len(evidence.request_violations) == 2
    assert browser.build_aggregate(evidence).status == browser.FAIL


SECRET = "SYNTHETIC-pw-DO-NOT-USE-31af"


def test_write_evidence_scrubs_a_leaked_secret_in_memory(tmp_path):
    evidence = _evidence(browser.PASS)
    evidence.cases.append(
        browser.CaseResult(
            "auth-login", "user", "desktop", browser.FAIL, f"timeout: fill({SECRET!r})"
        )
    )
    evidence.secrets = (SECRET,)
    browser.write_evidence(tmp_path, evidence)
    report = (tmp_path / "report.json").read_text()
    summary = (tmp_path / "summary.md").read_text()
    assert SECRET not in report
    assert SECRET not in summary
    assert browser.REDACTED in report
    assert browser.SANITIZATION_MARKER in report
    assert browser.SANITIZATION_MARKER in summary
    assert evidence.hygiene == browser.FAIL
    assert browser.artifacts_with_secrets(tmp_path, (SECRET,)) == []
    assert browser.build_aggregate(evidence).status == browser.FAIL


def test_write_evidence_scrubs_the_percent_encoded_variant(tmp_path):
    secret = "synthetic pw/with spaces"
    evidence = _evidence(browser.PASS)
    evidence.cases.append(
        browser.CaseResult(
            "auth-login",
            "user",
            "desktop",
            browser.FAIL,
            f"POST /login/?password={quote(secret, safe='')}",
        )
    )
    evidence.secrets = (secret,)
    browser.write_evidence(tmp_path, evidence)
    report = (tmp_path / "report.json").read_text()
    assert quote(secret, safe="") not in report
    assert browser.REDACTED in report
    assert evidence.hygiene == browser.FAIL


def test_write_evidence_reports_pass_when_nothing_leaks(tmp_path):
    evidence = _evidence(browser.PASS)
    evidence.secrets = ("SYNTHETIC-never-used",)
    browser.write_evidence(tmp_path, evidence)
    report = (tmp_path / "report.json").read_text()
    assert browser.SANITIZATION_MARKER not in report
    assert json.loads(report)["sanitization"] == browser.PASS
    assert evidence.hygiene == browser.PASS
    assert browser.artifacts_with_secrets(tmp_path, ("SYNTHETIC-never-used",)) == []


def test_artifacts_with_secrets_reads_the_written_bytes(tmp_path):
    (tmp_path / "report.json").write_text('{"detail": "SECRET-X"}')
    (tmp_path / "summary.md").write_text("clean")
    assert browser.artifacts_with_secrets(tmp_path, ("SECRET-X",)) == ["report.json"]


def test_sanitize_json_payload_removes_a_secret_before_printing():
    payload = {"status": "PASS", "cases": [{"detail": "fill('SECRET-Z')"}]}
    text, clean = browser.sanitize_json_payload(payload, ("SECRET-Z",))
    assert clean is False
    assert "SECRET-Z" not in text
    assert browser.REDACTED in text
    assert browser.SANITIZATION_MARKER in text


def test_sanitize_json_payload_keeps_a_clean_payload_untouched():
    text, clean = browser.sanitize_json_payload({"status": "PASS"}, ("SECRET-Z",))
    assert clean is True
    assert json.loads(text) == {"status": "PASS"}
    text, clean = browser.sanitize_json_payload({"status": "PASS"}, ())
    assert clean is True
    assert json.loads(text) == {"status": "PASS"}


class _RaisingLeakyRunner:
    """A case runner whose exception message carries a run secret."""

    def __init__(self, browser_module):
        self.browser = browser_module

    def __call__(self, ctx):
        raise AssertionError("login form refused for SECRET-USER")


def test_cmd_run_sanitizes_the_printed_payload(controller, monkeypatch, tmp_path):
    captured = _patch_run(monkeypatch, controller, tmp_path, runner=_RaisingLeakyRunner(browser))
    outcome = controller.cmd_run(
        "dev",
        feature="auth",
        roles=("user",),
        confirm_synthetic_data=True,
        viewport_names=("desktop",),
        driver_factory=captured["factory"],
    )
    assert "SECRET-USER" not in outcome.payload
    assert browser.REDACTED in outcome.payload
    assert json.loads(outcome.payload)["status"] == browser.FAIL
    report = (Path(outcome.evidence_dir) / "report.json").read_text()
    assert "SECRET-USER" not in report
    assert browser.SANITIZATION_MARKER in report


def test_cmd_run_downgrades_a_stdout_only_sanitization_failure(
    controller, monkeypatch, tmp_path
):
    captured = _patch_run(monkeypatch, controller, tmp_path)
    monkeypatch.setattr(browser, "EVIDENCE_ROOT", tmp_path / "evidence-SECRET-USER")
    outcome = controller.cmd_run(
        "dev",
        feature="auth",
        roles=("user",),
        confirm_synthetic_data=True,
        viewport_names=("desktop",),
        driver_factory=captured["factory"],
    )
    assert "SECRET-USER" not in outcome.payload
    assert browser.REDACTED in outcome.payload
    printed = json.loads(outcome.payload)
    assert printed[browser.SANITIZATION_KEY] == browser.FAIL
    assert printed["status"] == browser.FAIL
    assert printed["exit_code"] != 0
    assert any(browser.SANITIZATION_MARKER in reason for reason in printed["reasons"])
    assert outcome.status == browser.FAIL
    assert outcome.exit_code != 0
    assert any(browser.SANITIZATION_MARKER in reason for reason in outcome.reasons)
    evidence_dir = Path(outcome.evidence_dir)
    assert browser.artifacts_with_secrets(evidence_dir, ("SECRET-USER",)) == []


def test_cmd_run_keeps_a_clean_stdout_payload_passing(controller, monkeypatch, tmp_path):
    captured = _patch_run(monkeypatch, controller, tmp_path)
    outcome = controller.cmd_run(
        "dev",
        feature="auth",
        roles=("user",),
        confirm_synthetic_data=True,
        viewport_names=("desktop",),
        driver_factory=captured["factory"],
    )
    assert outcome.status == browser.PASS
    assert outcome.exit_code == 0
    printed = json.loads(outcome.payload)
    assert printed["status"] == browser.PASS
    assert printed["exit_code"] == 0


# ---------------------------------------------------------------------------
# Repair v3 — real Chromium boundaries with disposable 127.0.0.1 endpoints
# ---------------------------------------------------------------------------


def _browser_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            playwright.chromium.launch(headless=True).close()
    except Exception:  # no browser in the container image: honest skip
        return False
    return True


_BROWSER_AVAILABLE = _browser_available()


class _SyntheticOrigin:
    """A disposable 127.0.0.1 origin that counts accepts and requests."""

    def __init__(self) -> None:
        self.routes: dict[str, tuple[str, bytes, str, tuple[tuple[str, str], ...]]] = {}
        self.requests: list[str] = []
        self.accepts = 0
        self._lock = threading.Lock()
        self._server = _SyntheticServer(self)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def respond(self, path: str, *, html: str = "", redirect: str = "") -> None:
        if html:
            self.routes[path] = ("html", html.encode(), "text/html", ())
        elif redirect:
            self.routes[path] = ("redirect", redirect.encode(), "text/html", ())
        else:
            raise ValueError("a synthetic response needs html or a redirect")

    def respond_script(self, path: str, script: str, *, allowed_scope: str = "") -> None:
        headers = () if not allowed_scope else (("Service-Worker-Allowed", allowed_scope),)
        self.routes[path] = ("html", script.encode(), "application/javascript", headers)

    def note_request(self, path: str) -> None:
        with self._lock:
            self.requests.append(path)

    def note_accept(self) -> None:
        with self._lock:
            self.accepts += 1

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


class _SyntheticServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, endpoint: _SyntheticOrigin) -> None:
        self.endpoint = endpoint
        super().__init__(("127.0.0.1", 0), _make_synthetic_handler(endpoint))

    def get_request(self) -> tuple[Any, Any]:
        connection, address = super().get_request()
        self.endpoint.note_accept()
        return connection, address


def _make_synthetic_handler(endpoint: _SyntheticOrigin) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            endpoint.note_request(self.path)
            route = endpoint.routes.get(self.path)
            if route is None:
                self._respond(200, b"<html><body>default</body></html>", "text/html", ())
                return
            kind, payload, content_type, headers = route
            if kind == "redirect":
                self.send_response(302)
                self.send_header("Location", payload.decode())
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._respond(200, payload, content_type, headers)

        def _respond(
            self,
            status: int,
            body: bytes,
            content_type: str,
            headers: tuple[tuple[str, str], ...],
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            for name, value in headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _Handler


class _WebSocketProbe(threading.Thread):
    """Counts the TCP connections a websocket handshake would open."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self._socket = socket.socket()
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(5)
        self._socket.settimeout(0.5)
        self.host = f"127.0.0.1:{self._socket.getsockname()[1]}"
        self.accepts = 0
        self._stopped = False

    def run(self) -> None:
        while not self._stopped:
            try:
                connection, _ = self._socket.accept()
            except (TimeoutError, OSError):
                continue
            self.accepts += 1
            try:
                connection.settimeout(0.5)
                connection.recv(4096)
            except Exception:
                pass
            finally:
                connection.close()

    def stop(self) -> None:
        self._stopped = True
        self._socket.close()


class _AllowAllPolicy(browser.RequestPolicy):
    """Positive control: a policy that refuses nothing."""

    def decide(self, url: str, method: str) -> browser.PolicyDecision:
        return browser.PolicyDecision(True, "allowed", "positive control")


def _real_evidence(origin: str) -> browser.RunEvidence:
    evidence = browser.RunEvidence(
        run_id=RUN,
        feature="auth",
        target="synthetic",
        roles=("user",),
        viewports=("desktop",),
        started_at="2026-10-04T00:00:00+00:00",
    )
    evidence.cleanup = browser.PASS
    return evidence


def _real_driver(tmp_path, origin, cases, *, policy=None):
    session = browser.PlaywrightBrowser(base_url=origin)
    driver = browser.SmokeDriver(
        session=session,
        evidence_dir=tmp_path / "evidence",
        base_url=origin,
        case_table=lambda feature, viewport: cases,
        policy_case_table=lambda feature, viewport: (),
    )
    if policy is not None:
        driver.policy = policy
    return session, driver


def _navigation_case(ctx):
    try:
        browser._goto(ctx, "/painel/")
    except Exception as exc:
        return browser.CaseOutcome(browser.FAIL, f"navigation stopped: {type(exc).__name__}")
    return browser.CaseOutcome(browser.PASS, "navigation completed")


@pytest.mark.skipif(not _BROWSER_AVAILABLE, reason="no Chromium in this environment")
class TestRealBrowserBoundaries:
    def test_real_redirect_hop_never_reaches_the_forbidden_origin(self, tmp_path):
        allowed = _SyntheticOrigin()
        forbidden = _SyntheticOrigin()
        try:
            allowed.respond("/painel/", redirect=f"{allowed.origin}/censo/")
            allowed.respond("/censo/", redirect=f"{forbidden.origin}/painel/")
            forbidden.respond("/painel/", html="<html><body>forbidden</body></html>")
            session, driver = _real_driver(
                tmp_path, allowed.origin, (("navigate", _navigation_case),)
            )
            evidence = _real_evidence(allowed.origin)
            try:
                driver.execute(
                    evidence, feature="auth", roles=("user",), viewports=(browser.DESKTOP,)
                )
            finally:
                driver.close_browser()
            assert forbidden.accepts == 0, forbidden.requests
            assert forbidden.requests == []
            assert "/painel/" in allowed.requests and "/censo/" in allowed.requests
            assert any(forbidden.origin in entry for entry in evidence.request_violations)
            assert browser.build_aggregate(evidence).status == browser.FAIL
            print(
                f"[evidence] 302 hop: forbidden_accepts={forbidden.accepts} "
                f"forbidden_requests={forbidden.requests} allowed_requests={allowed.requests}"
            )
        finally:
            allowed.stop()
            forbidden.stop()

    def test_real_redirect_hop_control_reaches_the_forbidden_origin(self, tmp_path):
        allowed = _SyntheticOrigin()
        forbidden = _SyntheticOrigin()
        try:
            allowed.respond("/painel/", redirect=f"{allowed.origin}/censo/")
            allowed.respond("/censo/", redirect=f"{forbidden.origin}/painel/")
            forbidden.respond("/painel/", html="<html><body>forbidden</body></html>")
            session, driver = _real_driver(
                tmp_path,
                allowed.origin,
                (("navigate", _navigation_case),),
                policy=_AllowAllPolicy(origin="https://positive-control.verification.invalid"),
            )
            evidence = _real_evidence(allowed.origin)
            try:
                driver.execute(
                    evidence, feature="auth", roles=("user",), viewports=(browser.DESKTOP,)
                )
            finally:
                driver.close_browser()
            assert forbidden.accepts >= 1
            assert "/painel/" in forbidden.requests
            assert evidence.request_violations == []
            print(
                f"[evidence] 302 hop control: forbidden_accepts={forbidden.accepts} "
                f"forbidden_requests={forbidden.requests}"
            )
        finally:
            allowed.stop()
            forbidden.stop()

    def test_real_response_bodies_survive_the_cdp_hop_layer(self, tmp_path):
        allowed = _SyntheticOrigin()
        try:
            allowed.respond(
                "/painel/", html="<html><body><p id='marker'>PONTEIRO SINTETICO</p></body></html>"
            )

            def read_body(ctx):
                with ctx.page.expect_response(
                    lambda candidate: candidate.url == f"{allowed.origin}/painel/"
                ) as info:
                    browser._goto(ctx, "/painel/")
                response = info.value
                body = response.text()
                if "PONTEIRO SINTETICO" not in body:
                    raise AssertionError("the response body was rewritten by the hop layer")
                return browser.CaseOutcome(browser.PASS, f"response body read ({response.status})")

            session, driver = _real_driver(tmp_path, allowed.origin, (("navigate", read_body),))
            evidence = _real_evidence(allowed.origin)
            try:
                driver.execute(
                    evidence, feature="auth", roles=("user",), viewports=(browser.DESKTOP,)
                )
            finally:
                driver.close_browser()
            assert [case.status for case in evidence.cases] == [browser.PASS]
            assert evidence.request_violations == []
        finally:
            allowed.stop()

    def test_real_popup_is_blocked_before_its_first_request(self, tmp_path):
        allowed = _SyntheticOrigin()
        forbidden = _SyntheticOrigin()
        try:
            forbidden.respond("/painel/", html="<html><body>forbidden</body></html>")
            allowed.respond(
                "/painel/",
                html=(
                    "<html><body>"
                    f"<a id='popup' href='{forbidden.origin}/painel/' target='_blank'>pop</a>"
                    f"<script>window.open('{forbidden.origin}/painel/');</script>"
                    "</body></html>"
                ),
            )

            def popup_case(ctx):
                browser._goto(ctx, "/painel/")
                ctx.page.click("#popup")
                ctx.page.wait_for_timeout(400)
                return browser.CaseOutcome(browser.PASS, "popup attempts made")

            session, driver = _real_driver(tmp_path, allowed.origin, (("popup", popup_case),))
            evidence = _real_evidence(allowed.origin)
            try:
                driver.execute(
                    evidence, feature="auth", roles=("user",), viewports=(browser.DESKTOP,)
                )
            finally:
                driver.close_browser()
            assert forbidden.accepts == 0, forbidden.requests
            assert forbidden.requests == []
            assert any("popup" in entry for entry in evidence.request_violations)
            assert browser.build_aggregate(evidence).status == browser.FAIL
            print(
                f"[evidence] popup: forbidden_accepts={forbidden.accepts} "
                f"forbidden_requests={forbidden.requests} "
                f"violations={evidence.request_violations}"
            )
        finally:
            allowed.stop()
            forbidden.stop()

    def test_real_popup_control_reaches_the_forbidden_origin(self, tmp_path):
        allowed = _SyntheticOrigin()
        forbidden = _SyntheticOrigin()
        try:
            forbidden.respond("/painel/", html="<html><body>forbidden</body></html>")
            allowed.respond(
                "/painel/",
                html=(
                    "<html><body>"
                    f"<script>window.open('{forbidden.origin}/painel/');</script>"
                    "</body></html>"
                ),
            )
            self._raw_navigation(allowed.origin + "/painel/", control_wait=600)
            assert forbidden.accepts >= 1, "the popup control never reached the destination"
            assert "/painel/" in forbidden.requests
            print(
                f"[evidence] popup control: forbidden_accepts={forbidden.accepts} "
                f"forbidden_requests={forbidden.requests}"
            )
        finally:
            allowed.stop()
            forbidden.stop()

    def test_real_websocket_attempt_never_leaves_the_browser(self, tmp_path):
        allowed = _SyntheticOrigin()
        probe = _WebSocketProbe()
        probe.start()
        try:
            allowed.respond(
                "/painel/",
                html=(
                    "<html><body><script>"
                    f"const ws = new WebSocket('ws://{probe.host}/forbidden');"
                    "ws.onopen = () => { document.title = 'OPEN'; };"
                    "</script></body></html>"
                ),
            )

            def socket_case(ctx):
                browser._goto(ctx, "/painel/")
                ctx.page.wait_for_timeout(600)
                return browser.CaseOutcome(browser.PASS, "websocket attempted")

            session, driver = _real_driver(tmp_path, allowed.origin, (("socket", socket_case),))
            evidence = _real_evidence(allowed.origin)
            try:
                driver.execute(
                    evidence, feature="auth", roles=("user",), viewports=(browser.DESKTOP,)
                )
            finally:
                driver.close_browser()
            assert probe.accepts == 0
            assert any("websocket" in entry for entry in evidence.request_violations)
            assert browser.build_aggregate(evidence).status == browser.FAIL
            print(
                f"[evidence] websocket: probe_accepts={probe.accepts} "
                f"violations={evidence.request_violations}"
            )
        finally:
            probe.stop()
            allowed.stop()

    def test_real_websocket_control_reaches_the_probe(self):
        allowed = _SyntheticOrigin()
        probe = _WebSocketProbe()
        probe.start()
        try:
            allowed.respond(
                "/painel/",
                html=(
                    "<html><body><script>"
                    f"const ws = new WebSocket('ws://{probe.host}/forbidden');"
                    "ws.onerror = () => {};"
                    "</script></body></html>"
                ),
            )
            self._raw_navigation(allowed.origin + "/painel/", control_wait=800)
            assert probe.accepts >= 1, "the websocket control never reached the probe"
            print(f"[evidence] websocket control: probe_accepts={probe.accepts}")
        finally:
            probe.stop()
            allowed.stop()

    def test_real_service_worker_never_intercepts_fetches(self, tmp_path):
        allowed = _SyntheticOrigin()
        forbidden = _SyntheticOrigin()
        try:
            forbidden.respond("/sw-fetch", html="<html><body>forbidden</body></html>")
            self._service_worker_origin(allowed, forbidden)

            def worker_case(ctx):
                browser._goto(ctx, "/painel/")
                registered, controlled, status = self._service_worker_flow(
                    ctx.page, f"{allowed.origin}/painel/"
                )
                return browser.CaseOutcome(
                    browser.PASS,
                    f"registered={registered} controlled={controlled} fetch={status}",
                )

            session, driver = _real_driver(tmp_path, allowed.origin, (("sw", worker_case),))
            evidence = _real_evidence(allowed.origin)
            try:
                driver.execute(
                    evidence, feature="auth", roles=("user",), viewports=(browser.DESKTOP,)
                )
            finally:
                driver.close_browser()
            assert forbidden.accepts == 0, forbidden.requests
            assert forbidden.requests == []
            assert evidence.request_violations == []
            detail = evidence.cases[0].detail
            assert detail.endswith("controlled=0 fetch=200"), detail
            print(
                f"[evidence] service worker: forbidden_accepts={forbidden.accepts} "
                f"forbidden_requests={forbidden.requests} detail={evidence.cases[0].detail}"
            )
        finally:
            allowed.stop()
            forbidden.stop()

    def test_real_service_worker_control_reaches_the_forbidden_origin(self):
        from playwright.sync_api import sync_playwright

        allowed = _SyntheticOrigin()
        forbidden = _SyntheticOrigin()
        try:
            forbidden.respond("/sw-fetch", html="<html><body>forbidden</body></html>")
            self._service_worker_origin(allowed, forbidden)
            with sync_playwright() as playwright:
                raw = playwright.chromium.launch(headless=True)
                context = raw.new_context()
                try:
                    page = context.new_page()
                    page.goto(f"{allowed.origin}/painel/", wait_until="load", timeout=5000)
                    registered, controlled, _status = self._service_worker_flow(
                        page, f"{allowed.origin}/painel/"
                    )
                finally:
                    context.close()
                    raw.close()
            assert registered is True
            assert controlled == 1, "the control never got a controlling service worker"
            assert forbidden.accepts >= 1, "the service worker control never reached the origin"
            assert "/sw-fetch" in forbidden.requests
            print(
                f"[evidence] service worker control: forbidden_accepts={forbidden.accepts} "
                f"forbidden_requests={forbidden.requests} controlled={controlled}"
            )
        finally:
            allowed.stop()
            forbidden.stop()

    @staticmethod
    def _service_worker_flow(page, url: str) -> tuple[Any, Any, Any]:
        """Register a whole-origin worker, navigate under it and fetch /censo/."""
        registered = page.evaluate(
            "async () => { try {"
            " await navigator.serviceWorker.register('/static/sw.js', {scope: '/'});"
            " return true; } catch (error) { return false; } }"
        )
        page.wait_for_timeout(1200)
        page.goto(url, wait_until="load", timeout=5000)
        controlled = page.evaluate("() => (navigator.serviceWorker.controller ? 1 : 0)")
        status = page.evaluate(
            "async () => { try { const response = await fetch('/censo/');"
            " return response.status; } catch (error) { return 'ERR'; } }"
        )
        page.wait_for_timeout(400)
        return registered, controlled, status

    def test_real_fill_timeout_keeps_the_password_out_of_artifacts_and_stdout(
        self, controller, monkeypatch, tmp_path, capsys
    ):
        endpoint = _SyntheticOrigin()
        password = "SYNTHETIC-pw-DO-NOT-USE-4d81"
        try:
            endpoint.respond(
                "/login/",
                html=(
                    "<html><body><form method='post' action='/login/'>"
                    "<input id='id_username' name='username'>"
                    "<input id='id_password' name='password' readonly>"
                    "<button type='submit'>Entrar</button></form></body></html>"
                ),
            )
            monkeypatch.setattr(browser, "EVIDENCE_ROOT", tmp_path / "evidence")
            monkeypatch.setattr(controller, "_resolve_target", lambda name: _target())
            monkeypatch.setattr(controller, "cmd_open", lambda *a, **k: controller.OpenCredentials(
                run_id=RUN, passwords={"verify_user": password, "verify_admin": password + "-alt"},
                origin=endpoint.origin,
            ))
            monkeypatch.setattr(
                controller, "cmd_close", lambda *a, **k: controller.Verdict("PASS", True)
            )
            monkeypatch.setattr(
                controller, "_queue_metadata", lambda *a, **k: {"ingestion:total": 1}
            )

            def factory(**kwargs):
                kwargs.pop("origin", None)
                session = browser.PlaywrightBrowser(base_url=endpoint.origin, timeout_ms=1200)
                return browser.SmokeDriver(
                    session=session,
                    base_url=endpoint.origin,
                    case_table=lambda feature, viewport: (("auth-login", browser.case_login),),
                    policy_case_table=lambda feature, viewport: (),
                    **kwargs,
                )

            monkeypatch.setattr(controller, "_default_driver_factory", factory)
            exit_code = controller.main(
                [
                    "run",
                    "--target",
                    "dev",
                    "--feature",
                    "auth",
                    "--role",
                    "user",
                    "--viewport",
                    "desktop",
                    "--confirm-synthetic-data",
                ]
            )
            printed = capsys.readouterr().out
            evidence_dir = tmp_path / "evidence" / RUN
            report = (evidence_dir / "report.json").read_text()
            summary = (evidence_dir / "summary.md").read_text()
            assert exit_code == 1
            assert password not in report
            assert password not in summary
            assert password not in printed
            assert browser.REDACTED in report
            assert browser.SANITIZATION_MARKER in report
            assert browser.SANITIZATION_MARKER in summary
            assert json.loads(report)["sanitization"] == browser.FAIL
            assert browser.artifacts_with_secrets(evidence_dir, (password,)) == []
            print(
                f"[evidence] fill timeout: password_in_report={password in report} "
                f"password_in_summary={password in summary} "
                f"password_in_stdout={password in printed} "
                f"marker_in_report={browser.REDACTED in report} "
                f"hygiene={json.loads(report)['sanitization']} exit={exit_code}"
            )
        finally:
            endpoint.stop()

    @staticmethod
    def _raw_navigation(url: str, *, control_wait: int) -> None:
        """Positive control: a plain Chromium context without the driver."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            raw = playwright.chromium.launch(headless=True)
            context = raw.new_context()
            try:
                page = context.new_page()
                page.goto(url, wait_until="load", timeout=5000)
                page.wait_for_timeout(control_wait)
            finally:
                context.close()
                raw.close()

    @staticmethod
    def _service_worker_origin(allowed: _SyntheticOrigin, forbidden: _SyntheticOrigin) -> None:
        """An origin whose service worker proxies /censo/ fetches to another one.

        The worker script lives under the allowed static prefix and asks for the
        whole origin as scope, so a controlled page really routes through it.
        """
        allowed.respond("/painel/", html="<html><body>panel</body></html>")
        allowed.respond_script(
            "/static/sw.js",
            (
                "self.addEventListener('install', (event) => self.skipWaiting());"
                "self.addEventListener('activate',"
                " (event) => event.waitUntil(self.clients.claim()));"
                "self.addEventListener('fetch', (event) => {"
                " if (event.request.url.includes('/censo/')) {"
                f" event.respondWith(fetch('{forbidden.origin}/sw-fetch'));"
                " }"
                "});"
            ),
            allowed_scope="/",
        )
