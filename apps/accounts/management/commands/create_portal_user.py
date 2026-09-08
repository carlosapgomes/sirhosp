"""Provision portal users with a one-time provisional password (design D4).

Usage::

    python manage.py create_portal_user <username> --full-name "First Last"
    python manage.py create_portal_user --reset-password <username>

Create mode provisions an active common user (never staff/superuser) with a
random provisional password applied through ``set_password`` and a
``UserProfile`` flagged with ``must_change_password=True``; the plain
password is printed exactly once on stdout as
``temporary_password=<token>`` (never stored or logged elsewhere). Reset
mode reissues a provisional password for an existing user and re-arms the
flag — password-loss recovery without e-mail.
"""

from __future__ import annotations

import secrets
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import UserProfile

User = get_user_model()

TOKEN_LINE = "temporary_password={token}"


class Command(BaseCommand):
    help = (
        "Create an active common portal user with a one-time provisional "
        "password (or reissue one with --reset-password). The plain "
        "password is printed once on stdout and never stored."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("username", nargs="?", help="Portal username.")
        parser.add_argument(
            "--full-name",
            default="",
            help=(
                "Full display name; first word becomes first_name, the rest "
                "last_name (single word leaves last_name empty)."
            ),
        )
        parser.add_argument(
            "--reset-password",
            dest="reset_username",
            metavar="USERNAME",
            help="Reissue a provisional password for this existing user.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        username = options.get("username")
        reset_username = options.get("reset_username")
        if reset_username:
            if username:
                raise CommandError(
                    "Use only one mode: create (positional username) or "
                    "--reset-password <username>."
                )
            self._reissue_password(reset_username)
            return
        if not username:
            raise CommandError(
                "Usage: create_portal_user <username> [--full-name \"...\"] "
                "| create_portal_user --reset-password <username>"
            )
        self._create_user(username, options.get("full_name") or "")

    def _create_user(self, username: str, full_name: str) -> None:
        if User.objects.filter(username=username).exists():
            raise CommandError(
                f"Usuário '{username}' já existe; use --reset-password para "
                "reemitir a senha provisória."
            )
        first_name, last_name = self._split_full_name(full_name)
        token = secrets.token_urlsafe(12)
        user = User.objects.create_user(
            username=username,
            password=token,
            first_name=first_name,
            last_name=last_name,
        )
        user.is_active = True
        user.is_staff = False
        user.is_superuser = False
        user.save(update_fields=["is_active", "is_staff", "is_superuser"])
        UserProfile.objects.create(user=user, must_change_password=True)
        self.stdout.write(f"Usuário '{username}' criado com senha provisória.")
        self.stdout.write(TOKEN_LINE.format(token=token))

    def _reissue_password(self, username: str) -> None:
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist as exc:
            raise CommandError(
                f"Usuário '{username}' não encontrado."
            ) from exc
        token = secrets.token_urlsafe(12)
        user.set_password(token)
        user.save(update_fields=["password"])
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.must_change_password = True
        profile.save(update_fields=["must_change_password"])
        self.stdout.write(f"Senha provisória reemitida para '{username}'.")
        self.stdout.write(TOKEN_LINE.format(token=token))

    @staticmethod
    def _split_full_name(full_name: str) -> tuple[str, str]:
        """First word -> first_name; the stripped remainder -> last_name."""
        parts = full_name.strip().split()
        first_name = parts[0] if parts else ""
        last_name = " ".join(parts[1:])
        return first_name, last_name
