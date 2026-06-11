"""Tests for command argument compatibility.

Slice S7 (tasks.md 7.2):
- Verify ``extract_admissions`` and ``extract_deaths`` management commands
  still expose the existing ``--date``, ``--start-date``, and ``--end-date``
  CLI arguments.
"""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase


class TestExtractAdmissionsCommandArguments(TestCase):
    """Verify extract_admissions command parses date arguments."""

    def test_command_has_date_argument(self):
        """--date argument is accepted by the parser."""
        buf = StringIO()
        try:
            call_command("extract_admissions", "--date=01/06/2026", stdout=buf)
        except SystemExit:
            pass  # service will fail, but argument parsing must NOT raise
        output = buf.getvalue()
        # If the argument wasn't recognized, Django would print an error
        # message about unknown arguments.
        self.assertNotIn("unrecognized arguments", output)
        self.assertNotIn("error", output)

    def test_command_has_start_date_argument(self):
        """--start-date argument is accepted by the parser."""
        buf = StringIO()
        try:
            call_command(
                "extract_admissions",
                "--start-date=01/06/2026",
                "--end-date=05/06/2026",
                stdout=buf,
            )
        except SystemExit:
            pass
        output = buf.getvalue()
        self.assertNotIn("unrecognized arguments", output)

    def test_command_has_end_date_argument(self):
        """--end-date argument is accepted by the parser."""
        buf = StringIO()
        try:
            call_command(
                "extract_admissions",
                "--start-date=10/06/2026",
                "--end-date=15/06/2026",
                stdout=buf,
            )
        except SystemExit:
            pass
        output = buf.getvalue()
        self.assertNotIn("unrecognized arguments", output)

    def test_date_argument_parses_without_system_exit_from_parser(self):
        """The argument parser itself must not call sys.exit on valid args."""
        buf = StringIO()
        err_buf = StringIO()
        try:
            call_command(
                "extract_admissions",
                "--date=01/06/2026",
                stdout=buf,
                stderr=err_buf,
            )
        except SystemExit:
            # SystemExit from the service failure (missing credentials) is
            # expected and acceptable — but we must verify the parser itself
            # did not trigger it.
            pass
        # If the parser itself failed, stderr would contain "error:".
        self.assertNotIn("error:", err_buf.getvalue().lower())


class TestExtractDeathsCommandArguments(TestCase):
    """Verify extract_deaths command parses date arguments."""

    def test_command_has_date_argument(self):
        """--date argument is accepted by the parser."""
        buf = StringIO()
        try:
            call_command("extract_deaths", "--date=01/06/2026", stdout=buf)
        except SystemExit:
            pass
        output = buf.getvalue()
        self.assertNotIn("unrecognized arguments", output)

    def test_command_has_start_date_argument(self):
        """--start-date argument is accepted by the parser."""
        buf = StringIO()
        try:
            call_command(
                "extract_deaths",
                "--start-date=01/06/2026",
                "--end-date=05/06/2026",
                stdout=buf,
            )
        except SystemExit:
            pass
        output = buf.getvalue()
        self.assertNotIn("unrecognized arguments", output)

    def test_command_has_end_date_argument(self):
        """--end-date argument is accepted by the parser."""
        buf = StringIO()
        try:
            call_command(
                "extract_deaths",
                "--start-date=10/06/2026",
                "--end-date=15/06/2026",
                stdout=buf,
            )
        except SystemExit:
            pass
        output = buf.getvalue()
        self.assertNotIn("unrecognized arguments", output)

    def test_help_shows_date_arguments(self):
        """--help output lists --date, --start-date, and --end-date."""
        from apps.deaths.management.commands.extract_deaths import (
            Command as DeathsCommand,
        )

        cmd = DeathsCommand()
        parser = cmd.create_parser("./manage.py", "extract_deaths")

        help_text = parser.format_help()
        self.assertIn("--date", help_text)
        self.assertIn("--start-date", help_text)
        self.assertIn("--end-date", help_text)


class TestExtractAdmissionsHelpOutput(TestCase):
    """Verify admissions --help shows all expected date arguments."""

    def test_help_shows_date_arguments(self):
        """--help output lists --date, --start-date, and --end-date."""
        from apps.admissions.management.commands.extract_admissions import (
            Command as AdmissionsCommand,
        )

        cmd = AdmissionsCommand()
        parser = cmd.create_parser("./manage.py", "extract_admissions")

        help_text = parser.format_help()
        self.assertIn("--date", help_text)
        self.assertIn("--start-date", help_text)
        self.assertIn("--end-date", help_text)


class TestExtractOfficialCensusCommandArguments(TestCase):
    """Verify extract_official_census command exposes --date, --headless, --no-headless."""

    def test_command_has_date_argument(self):
        """--date argument is accepted by the parser."""
        buf = StringIO()
        try:
            call_command("extract_official_census", "--date=01/06/2026", stdout=buf)
        except SystemExit:
            pass
        output = buf.getvalue()
        self.assertNotIn("unrecognized arguments", output)

    def test_command_has_headless_argument(self):
        """--headless argument is accepted by the parser."""
        buf = StringIO()
        try:
            call_command("extract_official_census", "--headless", stdout=buf)
        except SystemExit:
            pass
        output = buf.getvalue()
        self.assertNotIn("unrecognized arguments", output)

    def test_command_has_no_headless_argument(self):
        """--no-headless argument is accepted by the parser."""
        buf = StringIO()
        try:
            call_command("extract_official_census", "--no-headless", stdout=buf)
        except SystemExit:
            pass
        output = buf.getvalue()
        self.assertNotIn("unrecognized arguments", output)

    def test_help_shows_all_arguments(self):
        """--help output lists --date, --headless, and --no-headless."""
        from apps.census.management.commands.extract_official_census import (
            Command as CensusCommand,
        )

        cmd = CensusCommand()
        parser = cmd.create_parser("./manage.py", "extract_official_census")

        help_text = parser.format_help()
        self.assertIn("--date", help_text)
        self.assertIn("--headless", help_text)
        self.assertIn("--no-headless", help_text)


class TestExtractDischargesCommandArguments(TestCase):
    """Verify extract_discharges command exposes --date, --headless, --no-headless."""

    def test_command_has_date_argument(self):
        """--date argument is accepted by the parser."""
        buf = StringIO()
        try:
            call_command("extract_discharges", "--date=01/06/2026", stdout=buf)
        except SystemExit:
            pass
        output = buf.getvalue()
        self.assertNotIn("unrecognized arguments", output)

    def test_command_has_headless_argument(self):
        """--headless argument is accepted by the parser."""
        buf = StringIO()
        try:
            call_command("extract_discharges", "--headless", stdout=buf)
        except SystemExit:
            pass
        output = buf.getvalue()
        self.assertNotIn("unrecognized arguments", output)

    def test_command_has_no_headless_argument(self):
        """--no-headless argument is accepted by the parser."""
        buf = StringIO()
        try:
            call_command("extract_discharges", "--no-headless", stdout=buf)
        except SystemExit:
            pass
        output = buf.getvalue()
        self.assertNotIn("unrecognized arguments", output)

    def test_help_shows_all_arguments(self):
        """--help output lists --date, --headless, and --no-headless."""
        from apps.discharges.management.commands.extract_discharges import (
            Command as DischargesCommand,
        )

        cmd = DischargesCommand()
        parser = cmd.create_parser("./manage.py", "extract_discharges")

        help_text = parser.format_help()
        self.assertIn("--date", help_text)
        self.assertIn("--headless", help_text)
        self.assertIn("--no-headless", help_text)
