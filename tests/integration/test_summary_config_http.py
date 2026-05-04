"""Integration tests for summary configuration page (STP-S7).

Tests the user-facing config endpoint:
- Authenticated access required
- GET shows enabled phase-2 LLM options
- GET shows default prompt selector + saved custom prompts
- POST with default (padrão) prompt enqueues run
- POST with custom prompt enqueues run
- POST with salvar_prompt=true requires title and persists template
- POST with saved_prompt_id uses selected prompt
- Invalid mode is rejected
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.test import Client
from django.urls import reverse

from apps.patients.models import Admission, Patient
from apps.summaries.models import SummaryRun, UserPromptTemplate

TZ = ZoneInfo("America/Sao_Paulo")

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_user(username="cfguser", password="testpass123"):
    from django.contrib.auth.models import User

    return User.objects.create_user(username=username, password=password)


def _make_admission(*, discharge_date: datetime | None = None) -> Admission:
    patient = Patient.objects.create(
        patient_source_key="CFG-P001",
        source_system="tasy",
        name="CFG TEST PATIENT",
    )
    return Admission.objects.create(
        patient=patient,
        source_admission_key="CFG-ADM",
        source_system="tasy",
        admission_date=datetime(2026, 4, 1, 10, 0, tzinfo=TZ),
        discharge_date=discharge_date,
        ward="Enfermaria A",
    )


def _config_url(admission: Admission) -> str:
    return reverse("summaries:summary_config", args=[admission.pk])


def _login(client: Client, user):
    client.force_login(user)


# ---------------------------------------------------------------------------
# Phase 2 env helper
# ---------------------------------------------------------------------------


def _setup_phase2_env(monkeypatch) -> None:
    """Set up two enabled phase-2 options for test rendering."""
    monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_LABEL", "GPT-4o (OpenAI)")
    monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_PROVIDER", "openai")
    monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_MODEL", "gpt-4o")
    monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_API_KEY", "sk-test-1")
    monkeypatch.setenv("SUMMARY_PHASE2_OPTION_1_ENABLED", "true")

    monkeypatch.setenv("SUMMARY_PHASE2_OPTION_2_LABEL", "Claude 3.5 (Anthropic)")
    monkeypatch.setenv("SUMMARY_PHASE2_OPTION_2_PROVIDER", "anthropic")
    monkeypatch.setenv("SUMMARY_PHASE2_OPTION_2_MODEL", "claude-3.5-sonnet")
    monkeypatch.setenv("SUMMARY_PHASE2_OPTION_2_BASE_URL", "https://api.anthropic.com/v1")
    monkeypatch.setenv("SUMMARY_PHASE2_OPTION_2_API_KEY", "sk-test-2")
    monkeypatch.setenv("SUMMARY_PHASE2_OPTION_2_ENABLED", "true")

    # Option 3 disabled — should NOT appear
    monkeypatch.setenv("SUMMARY_PHASE2_OPTION_3_LABEL", "Gemini (Google)")
    monkeypatch.setenv("SUMMARY_PHASE2_OPTION_3_PROVIDER", "google")
    monkeypatch.setenv("SUMMARY_PHASE2_OPTION_3_MODEL", "gemini-1.5-pro")
    monkeypatch.setenv("SUMMARY_PHASE2_OPTION_3_BASE_URL", "https://api.google.com/v1")
    monkeypatch.setenv("SUMMARY_PHASE2_OPTION_3_API_KEY", "sk-test-3")
    monkeypatch.setenv("SUMMARY_PHASE2_OPTION_3_ENABLED", "false")


# ---------------------------------------------------------------------------
# Anonymous access
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAnonymousAccessBlocked:
    """Anonymous users must be redirected to login."""

    def test_anonymous_get_redirects_to_login(self, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        client = Client()
        url = _config_url(admission)
        response = client.get(url)
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]

    def test_anonymous_post_redirects_to_login(self, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        client = Client()
        url = _config_url(admission)
        response = client.post(
            url,
            {"mode": "generate", "prompt_mode": "padrao"},
        )
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# GET: config page rendering
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestConfigPageRendering:
    """GET on config page must render form with correct options."""

    def test_get_returns_200_for_authenticated(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.get(_config_url(admission))
        assert response.status_code == 200

    def test_page_shows_enabled_llm_options(self, client, monkeypatch):
        """Enabled phase-2 options must appear; disabled ones must not."""
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.get(_config_url(admission))
        content = response.content.decode()

        # Enabled options visible
        assert "GPT-4o (OpenAI)" in content
        assert "Claude 3.5 (Anthropic)" in content
        # Disabled option NOT visible
        assert "Gemini" not in content
        # Have a dropdown/select with option indices
        assert "phase2_option_index" in content

    def test_page_shows_prompt_mode_selector(self, client, monkeypatch):
        """Form must include prompt_mode radio/select with padrão/custom."""
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.get(_config_url(admission))
        content = response.content.decode()

        assert "prompt_mode" in content
        assert "padrao" in content
        assert "custom" in content

    def test_page_shows_saved_prompts_when_available(
        self, client, monkeypatch
    ):
        """When user has saved prompts, they appear in the config page."""
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        user = _make_user()
        _login(client, user)

        # Create a saved prompt
        UserPromptTemplate.objects.create(
            owner=user,
            title="Meu Prompt Salvo",
            content="Conteúdo personalizado",
            is_public=False,
        )
        # Create a public prompt from another user
        other = _make_user(username="othercfguser")
        UserPromptTemplate.objects.create(
            owner=other,
            title="Prompt Público",
            content="Conteúdo público",
            is_public=True,
        )

        response = client.get(_config_url(admission))
        content = response.content.decode()
        assert "Meu Prompt Salvo" in content
        assert "Prompt Público" in content

    def test_page_shows_custom_prompt_textarea(self, client, monkeypatch):
        """Form must include textarea for custom prompt text."""
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.get(_config_url(admission))
        content = response.content.decode()
        assert "custom_prompt_text" in content

    def test_page_shows_salvar_prompt_checkbox_and_title(self, client, monkeypatch):
        """Form must include salvar_prompt checkbox and prompt_title field."""
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.get(_config_url(admission))
        content = response.content.decode()
        assert "salvar_prompt" in content
        assert "prompt_title" in content

    def test_page_has_mode_hidden_field(self, client, monkeypatch):
        """Form must carry the mode from the query param."""
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.get(
            _config_url(admission) + "?mode=generate"
        )
        content = response.content.decode()
        assert 'value="generate"' in content


# ---------------------------------------------------------------------------
# POST: config submission
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestConfigSubmissionDefaultPrompt:
    """POST with prompt_mode=padrao enqueues a SummaryRun."""

    def test_post_default_prompt_enqueues_run(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "1",
                "prompt_mode": "padrao",
            },
        )
        assert response.status_code == 302
        run = SummaryRun.objects.get(admission=admission)
        assert run.mode == "generate"
        assert run.status == SummaryRun.Status.QUEUED

    def test_post_default_prompt_redirects_to_status(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "1",
                "prompt_mode": "padrao",
            },
        )
        assert response.status_code == 302
        assert "/summaries/status/" in response.url  # type: ignore[attr-defined]


@pytest.mark.django_db
class TestConfigSubmissionCustomPrompt:
    """POST with prompt_mode=custom enqueues a SummaryRun."""

    def test_post_custom_prompt_enqueues_run(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "2",
                "prompt_mode": "custom",
                "custom_prompt_text": "Resuma os dados clínicos em português.",
            },
        )
        assert response.status_code == 302
        run = SummaryRun.objects.get(admission=admission)
        assert run.mode == "generate"
        assert run.status == SummaryRun.Status.QUEUED

    def test_post_custom_prompt_empty_text_is_ok(self, client, monkeypatch):
        """Custom prompt with empty text should still enqueue (uses default)."""
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.post(
            _config_url(admission),
            {
                "mode": "update",
                "phase2_option_index": "1",
                "prompt_mode": "custom",
                "custom_prompt_text": "",
            },
        )
        assert response.status_code == 302
        assert SummaryRun.objects.filter(admission=admission).exists()


@pytest.mark.django_db
class TestConfigSubmissionSavePrompt:
    """POST with salvar_prompt=true requires title and persists template."""

    def test_salvar_prompt_with_title_persists_template(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        user = _make_user()
        _login(client, user)
        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "1",
                "prompt_mode": "custom",
                "custom_prompt_text": "Resuma de forma objetiva.",
                "salvar_prompt": "on",
                "prompt_title": "Meu Resumo Objetivo",
                "prompt_is_public": "on",
            },
        )
        assert response.status_code == 302

        # Prompt was persisted
        saved = UserPromptTemplate.objects.get(owner=user, title="Meu Resumo Objetivo")
        assert saved.content == "Resuma de forma objetiva."
        assert saved.is_public is True

        # Run was enqueued
        assert SummaryRun.objects.filter(admission=admission).exists()

    def test_salvar_prompt_without_title_rejects(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        user = _make_user()
        _login(client, user)
        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "1",
                "prompt_mode": "custom",
                "custom_prompt_text": "Resuma de forma objetiva.",
                "salvar_prompt": "on",
                "prompt_title": "   ",  # whitespace-only = empty
                "prompt_is_public": "off",
            },
        )
        # Should re-render with error (no redirect)
        assert response.status_code == 200
        # No prompt persisted
        assert not UserPromptTemplate.objects.filter(
            owner=user, title__icontains="Meu Resumo"
        ).exists()
        # No run enqueued
        assert not SummaryRun.objects.filter(admission=admission).exists()

    def test_salvar_prompt_without_text_still_saves(self, client, monkeypatch):
        """salvar_prompt with title but empty text is allowed (template with empty body)."""
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        user = _make_user()
        _login(client, user)
        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "1",
                "prompt_mode": "custom",
                "custom_prompt_text": "",
                "salvar_prompt": "on",
                "prompt_title": "Template Vazio",
            },
        )
        assert response.status_code == 302
        saved = UserPromptTemplate.objects.get(owner=user, title="Template Vazio")
        assert saved.content == ""


@pytest.mark.django_db
class TestConfigSubmissionSavedPrompt:
    """POST with saved_prompt_id uses a previously saved prompt."""

    def test_post_with_saved_prompt_id_enqueues_run(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        user = _make_user()
        _login(client, user)

        saved = UserPromptTemplate.objects.create(
            owner=user,
            title="Prompt Reutilizado",
            content="Conteúdo reutilizável de prompt",
            is_public=False,
        )

        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "1",
                "prompt_mode": "custom",
                "saved_prompt_id": str(saved.pk),
            },
        )
        assert response.status_code == 302
        assert SummaryRun.objects.filter(admission=admission).exists()


@pytest.mark.django_db
class TestConfigSubmissionInvalidMode:
    """Invalid mode is rejected on config POST."""

    def test_invalid_mode_rejected(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.post(
            _config_url(admission),
            {
                "mode": "invalid_mode",
                "phase2_option_index": "1",
                "prompt_mode": "padrao",
            },
        )
        assert response.status_code == 200
        assert not SummaryRun.objects.filter(admission=admission).exists()


@pytest.mark.django_db
class TestConfigSubmissionMissingFields:
    """Required fields validation on config POST."""

    def test_missing_mode_rejected(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.post(
            _config_url(admission),
            {
                "phase2_option_index": "1",
                "prompt_mode": "padrao",
            },
        )
        assert response.status_code == 200
        assert not SummaryRun.objects.filter(admission=admission).exists()

    def test_missing_prompt_mode_rejected(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "1",
            },
        )
        assert response.status_code == 200
        assert not SummaryRun.objects.filter(admission=admission).exists()


# ---------------------------------------------------------------------------
# STP-S7-F1: Strict validation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPhase2OptionIndexValidation:
    """phase2_option_index must be required and valid when options exist."""

    def test_missing_phase2_option_index_rejected(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "prompt_mode": "padrao",
            },
        )
        assert response.status_code == 200
        assert not SummaryRun.objects.filter(admission=admission).exists()

    def test_phase2_option_index_non_integer_rejected(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "abc",
                "prompt_mode": "padrao",
            },
        )
        assert response.status_code == 200
        assert not SummaryRun.objects.filter(admission=admission).exists()

    def test_phase2_option_index_out_of_range_rejected(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "99",
                "prompt_mode": "padrao",
            },
        )
        assert response.status_code == 200
        assert not SummaryRun.objects.filter(admission=admission).exists()

    def test_phase2_option_index_disabled_option_rejected(self, client, monkeypatch):
        """Option 3 is disabled — it must not be accepted even if index=3."""
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "3",
                "prompt_mode": "padrao",
            },
        )
        assert response.status_code == 200
        assert not SummaryRun.objects.filter(admission=admission).exists()

    def test_valid_phase2_option_still_enqueues(self, client, monkeypatch):
        """Valid option 1 still works (regression test)."""
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "1",
                "prompt_mode": "padrao",
            },
        )
        assert response.status_code == 302
        assert SummaryRun.objects.filter(admission=admission).exists()


@pytest.mark.django_db
class TestSavedPromptIdValidation:
    """saved_prompt_id must refer to an accessible prompt."""

    def test_saved_prompt_id_nonexistent_rejected(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "1",
                "prompt_mode": "custom",
                "saved_prompt_id": "99999",
            },
        )
        assert response.status_code == 200
        assert not SummaryRun.objects.filter(admission=admission).exists()

    def test_saved_prompt_id_private_from_other_user_rejected(
        self, client, monkeypatch
    ):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        user = _make_user()
        _login(client, user)

        other = _make_user(username="privateguy")
        private_prompt = UserPromptTemplate.objects.create(
            owner=other,
            title="Prompt Secreto",
            content="Conteúdo privado",
            is_public=False,
        )

        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "1",
                "prompt_mode": "custom",
                "saved_prompt_id": str(private_prompt.pk),
            },
        )
        assert response.status_code == 200
        assert not SummaryRun.objects.filter(admission=admission).exists()

    def test_saved_prompt_id_public_from_other_user_accepted(
        self, client, monkeypatch
    ):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        user = _make_user()
        _login(client, user)

        other = _make_user(username="publicguy")
        public_prompt = UserPromptTemplate.objects.create(
            owner=other,
            title="Prompt Público",
            content="Conteúdo público",
            is_public=True,
        )

        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "1",
                "prompt_mode": "custom",
                "saved_prompt_id": str(public_prompt.pk),
            },
        )
        assert response.status_code == 302
        assert SummaryRun.objects.filter(admission=admission).exists()


@pytest.mark.django_db
class TestPhase2ConfigPersistedOnRun:
    """Effective choices are stored in phase2_config_json on SummaryRun."""

    def test_default_prompt_config_persisted(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "1",
                "prompt_mode": "padrao",
            },
        )
        assert response.status_code == 302
        run = SummaryRun.objects.get(admission=admission)
        config = run.phase2_config_json
        assert config["prompt_mode"] == "padrao"
        assert config["phase2_option_index"] == 1
        assert config["phase2_provider"] == "openai"
        assert config["phase2_model"] == "gpt-4o"

    def test_custom_prompt_config_persisted(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "2",
                "prompt_mode": "custom",
                "custom_prompt_text": "Resuma em tópicos.",
            },
        )
        assert response.status_code == 302
        run = SummaryRun.objects.get(admission=admission)
        config = run.phase2_config_json
        assert config["prompt_mode"] == "custom"
        assert config["phase2_option_index"] == 2
        assert config["phase2_provider"] == "anthropic"
        assert config["phase2_model"] == "claude-3.5-sonnet"
        assert config["prompt_text"] == "Resuma em tópicos."

    def test_saved_prompt_config_persisted(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        user = _make_user()
        _login(client, user)

        saved = UserPromptTemplate.objects.create(
            owner=user,
            title="Meu Prompt",
            content="Conteúdo salvo do prompt",
        )

        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "1",
                "prompt_mode": "custom",
                "saved_prompt_id": str(saved.pk),
            },
        )
        assert response.status_code == 302
        run = SummaryRun.objects.get(admission=admission)
        config = run.phase2_config_json
        assert config["prompt_mode"] == "custom"
        assert config["prompt_text"] == "Conteúdo salvo do prompt"


# ---------------------------------------------------------------------------
# STP-S7-F2: API key not persisted + data migration
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestApiKeyNotPersisted:
    """phase2_api_key must never be stored in phase2_config_json."""

    def test_default_prompt_no_api_key_persisted(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "1",
                "prompt_mode": "padrao",
            },
        )
        assert response.status_code == 302
        run = SummaryRun.objects.get(admission=admission)
        config = run.phase2_config_json
        assert "phase2_api_key" not in config

    def test_custom_prompt_no_api_key_persisted(self, client, monkeypatch):
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "2",
                "prompt_mode": "custom",
                "custom_prompt_text": "Resuma.",
            },
        )
        assert response.status_code == 302
        run = SummaryRun.objects.get(admission=admission)
        config = run.phase2_config_json
        assert "phase2_api_key" not in config

    def test_persisted_config_still_has_provider_model(self, client, monkeypatch):
        """Even though api_key is stripped, provider/model still present."""
        _setup_phase2_env(monkeypatch)
        admission = _make_admission()
        _login(client, _make_user())
        response = client.post(
            _config_url(admission),
            {
                "mode": "generate",
                "phase2_option_index": "1",
                "prompt_mode": "padrao",
            },
        )
        assert response.status_code == 302
        run = SummaryRun.objects.get(admission=admission)
        config = run.phase2_config_json
        assert config["phase2_provider"] == "openai"
        assert config["phase2_model"] == "gpt-4o"
        assert config["phase2_option_index"] == 1


@pytest.mark.django_db
class TestPhase2ConfigMigrationSanitization:
    """Data migration removes phase2_api_key from legacy records."""

    def test_legacy_api_key_removed_by_migration(self):
        """Run the data migration function directly; verify phase2_api_key stripped."""
        from datetime import date
        from importlib import import_module

        mod = import_module(
            "apps.summaries.migrations"
            ".0006_remove_phase2_api_key_from_config"
        )
        remove_phase2_api_key = mod.remove_phase2_api_key

        # Create a tainted SummaryRun with api_key in phase2_config_json
        patient = Patient.objects.create(
            patient_source_key="MIG-P001",
            source_system="tasy",
            name="MIG TEST PATIENT",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="MIG-ADM",
            source_system="tasy",
            admission_date=datetime(2026, 4, 1, 10, 0, tzinfo=TZ),
        )
        run = SummaryRun.objects.create(
            admission=admission,
            mode="generate",
            target_end_date=date.today(),
            status="queued",
            phase2_config_json={
                "prompt_mode": "padrao",
                "phase2_option_index": 1,
                "phase2_provider": "openai",
                "phase2_model": "gpt-4o",
                "phase2_api_key": "sk-should-not-be-here",
                "prompt_text": None,
            },
        )

        # Run sanitization function directly
        from django.apps import apps as django_apps

        remove_phase2_api_key(django_apps, None)

        run.refresh_from_db()
        config = run.phase2_config_json
        assert "phase2_api_key" not in config
        # Other fields preserved
        assert config["phase2_provider"] == "openai"
        assert config["phase2_model"] == "gpt-4o"
        assert config["phase2_option_index"] == 1

    def test_clean_record_unchanged_by_migration(self):
        """Records without api_key are not modified by sanitization."""
        from datetime import date
        from importlib import import_module

        mod = import_module(
            "apps.summaries.migrations"
            ".0006_remove_phase2_api_key_from_config"
        )
        remove_phase2_api_key = mod.remove_phase2_api_key

        patient = Patient.objects.create(
            patient_source_key="MIG-P002",
            source_system="tasy",
            name="MIG CLEAN",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="MIG-ADM2",
            source_system="tasy",
            admission_date=datetime(2026, 4, 1, 10, 0, tzinfo=TZ),
        )
        run = SummaryRun.objects.create(
            admission=admission,
            mode="generate",
            target_end_date=date.today(),
            status="queued",
            phase2_config_json={
                "prompt_mode": "custom",
                "phase2_option_index": 2,
                "phase2_provider": "anthropic",
                "phase2_model": "claude-3.5-sonnet",
                "prompt_text": "Resuma.",
            },
        )

        from django.apps import apps as django_apps

        remove_phase2_api_key(django_apps, None)

        run.refresh_from_db()
        config = run.phase2_config_json
        assert config["phase2_provider"] == "anthropic"
        assert config["phase2_model"] == "claude-3.5-sonnet"
        assert config["prompt_text"] == "Resuma."
