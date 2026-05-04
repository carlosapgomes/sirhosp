"""Integration tests for UserPromptTemplate HTTP CRUD and permissions (STP-S5).

Tests the user-facing prompt library endpoints:
- Create prompt with mandatory title
- List own + public prompts
- Edit/delete own prompts only
- Block edit/delete of third-party prompts
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from apps.summaries.models import UserPromptTemplate

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_user(username="promptowner", password="testpass123"):
    from django.contrib.auth.models import User

    return User.objects.create_user(username=username, password=password)


def _make_other_user():
    return _make_user(username="otheruser", password="otherpass123")


def _login(client: Client, user):
    client.force_login(user)


def _make_prompt(owner, *, title="Meu Prompt", content="Conteúdo do prompt",
                 is_public=False) -> UserPromptTemplate:
    return UserPromptTemplate.objects.create(
        owner=owner,
        title=title,
        content=content,
        is_public=is_public,
    )


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def _prompt_list_url() -> str:
    return reverse("summaries:prompt_list")


def _prompt_create_url() -> str:
    return reverse("summaries:prompt_create")


def _prompt_edit_url(pk: int) -> str:
    return reverse("summaries:prompt_edit", args=[pk])


def _prompt_delete_url(pk: int) -> str:
    return reverse("summaries:prompt_delete", args=[pk])


# ---------------------------------------------------------------------------
# Anonymous access
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAnonymousAccessBlocked:
    """Anonymous users must be redirected to login."""

    def test_anonymous_list_redirects_to_login(self):
        client = Client()
        response = client.get(_prompt_list_url())
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]

    def test_anonymous_create_get_redirects_to_login(self):
        client = Client()
        response = client.get(_prompt_create_url())
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]

    def test_anonymous_create_post_redirects_to_login(self):
        client = Client()
        response = client.post(_prompt_create_url(), {
            "title": "Teste",
            "content": "Conteúdo",
        })
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]
        assert UserPromptTemplate.objects.count() == 0


# ---------------------------------------------------------------------------
# Create prompt
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCreatePrompt:
    """Tests for prompt creation endpoint."""

    def test_create_prompt_success_redirects_to_list(self):
        """POST with valid data creates a prompt and redirects to list."""
        user = _make_user()
        client = Client()
        _login(client, user)

        response = client.post(_prompt_create_url(), {
            "title": "Meu Prompt Legal",
            "content": "Este é o conteúdo.",
            "is_public": "on",
        })

        assert response.status_code == 302
        prompt = UserPromptTemplate.objects.get()
        assert prompt.title == "Meu Prompt Legal"
        assert prompt.content == "Este é o conteúdo."
        assert prompt.is_public is True
        assert prompt.owner_id == user.pk

    def test_create_prompt_defaults_to_private(self):
        """Without is_public checkbox, prompt is private."""
        user = _make_user()
        client = Client()
        _login(client, user)

        response = client.post(_prompt_create_url(), {
            "title": "Prompt Privado",
            "content": "Secreto",
        })

        assert response.status_code == 302
        prompt = UserPromptTemplate.objects.get()
        assert prompt.is_public is False

    def test_create_prompt_title_required(self):
        """Empty title returns form error (200 with errors)."""
        user = _make_user()
        client = Client()
        _login(client, user)

        response = client.post(_prompt_create_url(), {
            "title": "",
            "content": "Conteúdo sem título",
        })

        assert response.status_code == 200
        assert UserPromptTemplate.objects.count() == 0
        content = response.content.decode("utf-8").lower()
        # Django form error for required field
        assert "obrigat" in content or "required" in content or "campo" in content

    def test_create_prompt_content_required(self):
        """Empty content returns form error."""
        user = _make_user()
        client = Client()
        _login(client, user)

        response = client.post(_prompt_create_url(), {
            "title": "Título Válido",
            "content": "",
        })

        assert response.status_code == 200
        assert UserPromptTemplate.objects.count() == 0


# ---------------------------------------------------------------------------
# List prompts
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestListPrompts:
    """Tests for prompt listing endpoint."""

    def test_list_shows_own_prompts(self):
        """Owner can see their own prompts."""
        user = _make_user()
        _make_prompt(user, title="Prompt A", is_public=False)
        _make_prompt(user, title="Prompt B", is_public=True)
        client = Client()
        _login(client, user)

        response = client.get(_prompt_list_url())
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Prompt A" in content
        assert "Prompt B" in content

    def test_list_shows_public_prompts_from_others(self):
        """User can see public prompts from other owners."""
        other = _make_other_user()
        _make_prompt(other, title="Público do Outro", is_public=True)
        _make_prompt(other, title="Privado do Outro", is_public=False)

        user = _make_user()
        client = Client()
        _login(client, user)

        response = client.get(_prompt_list_url())
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Público do Outro" in content
        assert "Privado do Outro" not in content

    def test_list_excludes_private_from_others(self):
        """Private prompts from other users are NOT visible."""
        other = _make_other_user()
        _make_prompt(other, title="Secreto", is_public=False)

        user = _make_user()
        client = Client()
        _login(client, user)

        response = client.get(_prompt_list_url())
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        assert "Secreto" not in content


# ---------------------------------------------------------------------------
# Edit prompt
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEditPrompt:
    """Tests for prompt edit endpoint."""

    def test_owner_can_edit_own_prompt(self):
        """Owner can update title/content/visibility of own prompt."""
        user = _make_user()
        prompt = _make_prompt(user, title="Original", content="Antigo",
                              is_public=False)
        client = Client()
        _login(client, user)

        response = client.post(_prompt_edit_url(prompt.pk), {
            "title": "Alterado",
            "content": "Novo conteúdo",
            "is_public": "on",
        })

        assert response.status_code == 302
        prompt.refresh_from_db()
        assert prompt.title == "Alterado"
        assert prompt.content == "Novo conteúdo"
        assert prompt.is_public is True

    def test_non_owner_cannot_edit_third_party_prompt(self):
        """User cannot edit a prompt owned by someone else."""
        owner = _make_user()
        prompt = _make_prompt(owner, title="Do Dono", content="Original",
                              is_public=True)

        other_user = _make_other_user()
        client = Client()
        _login(client, other_user)

        response = client.post(_prompt_edit_url(prompt.pk), {
            "title": "Roubo",
            "content": "Modificado",
        })

        # Should be denied: 403 or 404
        assert response.status_code in (403, 404)
        prompt.refresh_from_db()
        assert prompt.title == "Do Dono"

    def test_edit_non_existent_returns_404(self):
        """Editing non-existent prompt returns 404."""
        user = _make_user()
        client = Client()
        _login(client, user)

        response = client.post(_prompt_edit_url(99999), {
            "title": "X",
            "content": "Y",
        })
        assert response.status_code == 404

    def test_edit_title_required(self):
        """Empty title on edit returns form error."""
        user = _make_user()
        prompt = _make_prompt(user, title="Original", content="Antigo")
        client = Client()
        _login(client, user)

        response = client.post(_prompt_edit_url(prompt.pk), {
            "title": "",
            "content": "Novo conteúdo",
        })

        assert response.status_code == 200
        prompt.refresh_from_db()
        assert prompt.title == "Original"  # unchanged


# ---------------------------------------------------------------------------
# Delete prompt
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeletePrompt:
    """Tests for prompt deletion endpoint."""

    def test_owner_can_delete_own_prompt(self):
        """Owner can delete own prompt."""
        user = _make_user()
        prompt = _make_prompt(user)
        client = Client()
        _login(client, user)

        response = client.post(_prompt_delete_url(prompt.pk))

        assert response.status_code == 302
        assert UserPromptTemplate.objects.filter(pk=prompt.pk).count() == 0

    def test_non_owner_cannot_delete_third_party_prompt(self):
        """User cannot delete a prompt owned by someone else."""
        owner = _make_user()
        prompt = _make_prompt(owner, title="Protegido", is_public=True)

        other_user = _make_other_user()
        client = Client()
        _login(client, other_user)

        response = client.post(_prompt_delete_url(prompt.pk))

        # Should be denied: 403 or 404
        assert response.status_code in (403, 404)
        assert UserPromptTemplate.objects.filter(pk=prompt.pk).count() == 1

    def test_delete_non_existent_returns_404(self):
        """Deleting non-existent prompt returns 404."""
        user = _make_user()
        client = Client()
        _login(client, user)

        response = client.post(_prompt_delete_url(99999))
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Navigation links
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestNavigation:
    """Tests for navigation and link rendering."""

    def test_list_page_shows_create_link(self):
        """List page includes a link to create new prompt."""
        user = _make_user()
        client = Client()
        _login(client, user)

        response = client.get(_prompt_list_url())
        assert response.status_code == 200
        content = response.content.decode("utf-8").lower()
        assert "criar" in content or "novo" in content or "create" in content

    def test_list_page_shows_edit_links_for_own_prompts(self):
        """List page shows edit link for own prompts."""
        user = _make_user()
        _make_prompt(user, title="Editável")
        client = Client()
        _login(client, user)

        response = client.get(_prompt_list_url())
        assert response.status_code == 200
        content = response.content.decode("utf-8").lower()
        assert "editar" in content or "edit" in content

    def test_list_page_hides_edit_links_for_public_third_party(self):
        """List page does NOT show edit links for public prompts from others."""
        other = _make_other_user()
        prompt = _make_prompt(other, title="Público Alheio", is_public=True)

        user = _make_user()
        client = Client()
        _login(client, user)

        response = client.get(_prompt_list_url())
        assert response.status_code == 200
        content = response.content.decode("utf-8")
        # The prompt title must be visible...
        assert "Público Alheio" in content
        # ...but the edit URL for that specific prompt must NOT be present
        edit_url = _prompt_edit_url(prompt.pk)
        assert edit_url not in content
