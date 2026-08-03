"""Tests for the pure decision logic.

These tests import only `checks`, which imports nothing from `cat`. They need
no running Cheshire Cat, no container and no core dependency: `pytest` alone is
enough.

    python -m pytest
"""

import sys
from pathlib import Path

import pytest

# The Cat imports every .py in the plugin folder, this file included, under a
# package name where a bare `import checks` does not resolve — which would make
# the core log a plugin load error on every activation. Putting the plugin
# folder on the path fixes that without weakening the import: a genuine
# breakage still fails the tests instead of skipping them.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from checks import (  # noqa: E402  (import after the path fix, on purpose)
    DEFAULT_MAX_MESSAGE_CHARS,
    VERDICT_MESSAGE_TOO_LONG,
    check_length,
    extract_text,
    run_input_checks,
)


class TestCheckLength:
    def test_short_message_passes(self):
        assert check_length("How do I activate the VPN?", max_chars=100) is None

    def test_message_exactly_at_the_limit_passes(self):
        # The limit is inclusive: only what exceeds it is stopped.
        assert check_length("a" * 100, max_chars=100) is None

    def test_message_one_character_over_the_limit_is_stopped(self):
        assert check_length("a" * 101, max_chars=100) == VERDICT_MESSAGE_TOO_LONG

    def test_empty_message_passes_this_check(self):
        # Emptiness is a separate Fase 2 control, not this one's business.
        assert check_length("", max_chars=100) is None

    @pytest.mark.parametrize("disabled", [0, -1])
    def test_non_positive_limit_disables_the_check(self, disabled):
        assert check_length("a" * 10_000, max_chars=disabled) is None

    def test_default_limit_is_used_when_not_specified(self):
        assert check_length("a" * (DEFAULT_MAX_MESSAGE_CHARS + 1)) == (
            VERDICT_MESSAGE_TOO_LONG
        )
        assert check_length("a" * DEFAULT_MAX_MESSAGE_CHARS) is None

    def test_length_is_counted_in_characters_not_bytes(self):
        # Accented and non-latin characters must not count double, otherwise
        # Italian questions would be stopped earlier than English ones.
        assert check_length("è" * 100, max_chars=100) is None


class TestExtractText:
    def test_reads_a_mapping(self):
        assert extract_text({"text": "hello"}) == "hello"

    def test_reads_an_object_with_a_text_attribute(self):
        class FakeUserMessage:
            text = "hello"

        assert extract_text(FakeUserMessage()) == "hello"

    @pytest.mark.parametrize(
        "payload", [{}, {"text": None}, {"text": ""}, object(), None]
    )
    def test_missing_or_empty_text_becomes_an_empty_string(self, payload):
        # Never None: every caller can treat the result as a string.
        assert extract_text(payload) == ""


class TestRunInputChecks:
    def test_returns_none_when_every_check_passes(self):
        assert run_input_checks("How do I activate the VPN?", max_chars=100) is None

    def test_returns_the_verdict_of_the_failing_check(self):
        assert run_input_checks("a" * 101, max_chars=100) == VERDICT_MESSAGE_TOO_LONG
