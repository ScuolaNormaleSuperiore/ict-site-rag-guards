"""Tests for the pure decision logic.

These tests import only `checks`, which imports nothing from `cat`. They need
no running Cheshire Cat, no container and no core dependency: `pytest` alone is
enough.

    python -m pytest
"""

import sys
import time
from pathlib import Path
from types import SimpleNamespace

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
    VERDICT_PERSONAL_DATA,
    check_length,
    check_personal_data,
    extract_text,
    matched_personal_data_kinds,
    phone_number_types,
    run_input_checks,
)

HELP_DESK = "helpdesk@example.org"

# Codice fiscali whose check character is correct. The first two are the
# vectors validator libraries use; the third is a female code, where the day
# carries the +40 offset.
VALID_CODICE_FISCALE = "RCCMNL83S18D969H"
VALID_CODICE_FISCALE_2 = "MRTMTT25D09F205Z"
VALID_CODICE_FISCALE_FEMALE = "CNTCHR83T41D969D"

# The example copied all over the internet. Its shape is right and its check
# character is wrong — the correct one is Q — so it is exactly what tells a
# checksum apart from a bare regex.
FABRICATED_CODICE_FISCALE = "RSSMRA85M01H501Z"

VALID_IBAN_IT = "IT60X0542811101000000123456"
VALID_IBAN_DE = "DE89370400440532013000"
BROKEN_IBAN = "IT60X0542811101000000123457"


def config(**overrides):
    """A stand-in for the settings model, exposing what the checks read."""
    values = {
        "max_message_chars": DEFAULT_MAX_MESSAGE_CHARS,
        "detect_email": True,
        "detect_codice_fiscale": True,
        "detect_iban": True,
        "detect_phone": True,
        "help_desk_email": HELP_DESK,
        "phone_region": "IT",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


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


class TestCheckPersonalData:
    @pytest.mark.parametrize(
        "message",
        [
            "Non riesco ad accedere con mario.rossi@sns.it, potete controllare?",
            f"Il mio codice fiscale è {VALID_CODICE_FISCALE}, mi servono le credenziali",
            f"My tax code is {VALID_CODICE_FISCALE_2}",
            f"Codice fiscale {VALID_CODICE_FISCALE_FEMALE} per la registrazione",
            f"Il mio IBAN è {VALID_IBAN_IT}",
            f"Here is my IBAN: {VALID_IBAN_DE}",
            "Chiamatemi al 3401234567 per il reset",
            "Chiamatemi al +39 340 1234567",
            # Landlines, in the shapes people actually write them.
            "Chiamatemi allo 0502509111",
            "Il numero è 050 509111",
            "Telefono 06 1234567",
            "Chiamare 011-1234567",
            "Ufficio: 0125 123456",
        ],
    )
    def test_personal_data_is_stopped(self, message):
        assert check_personal_data(message, allowed_email=HELP_DESK) == (
            VERDICT_PERSONAL_DATA
        )

    @pytest.mark.parametrize(
        "message",
        [
            # The false positives that matter on an ICT help desk: error codes,
            # ports, versions and dates are numeric and must pass.
            "Ricevo l'errore 0x80070005 sulla porta 8080, il PC è Windows 11",
            "La riunione è il 01.02.2026 alle 14, come attivo la VPN?",
            "Come attivo la VPN dal portatile aziendale?",
            "How do I reset my password?",
            # Right shape, wrong check character: not a codice fiscale.
            f"Codice fiscale {FABRICATED_CODICE_FISCALE}",
            # Right shape, failing mod-97: not an IBAN.
            f"IBAN {BROKEN_IBAN}",
        ],
    )
    def test_messages_without_personal_data_pass(self, message):
        assert check_personal_data(message, allowed_email=HELP_DESK) is None

    def test_the_help_desk_address_is_not_personal_data(self):
        # A user saying they already wrote to the Help Desk must be answered,
        # not refused.
        message = f"Ho scritto a {HELP_DESK} tre giorni fa e non ho risposta"
        assert check_personal_data(message, allowed_email=HELP_DESK) is None

    def test_another_address_alongside_the_help_desk_one_still_blocks(self):
        message = f"Ho scritto a {HELP_DESK} da mario.rossi@sns.it"
        assert check_personal_data(message, allowed_email=HELP_DESK) == (
            VERDICT_PERSONAL_DATA
        )

    @pytest.mark.parametrize(
        "message",
        [
            "La riunione è il 01.02.2026 alle 14",
            "La riunione è il 01/02/2026 alle 14",
            "Scadenza 01-02-2026",
            "Data 20260201",
            "Alle 09.30 non funzionava",
            "Ho aggiornato alle 08:45:00",
        ],
    )
    def test_dates_and_times_are_not_phone_numbers(self, message):
        # The reason for validating against a numbering plan instead of matching
        # a shape: the looser leniency levels accept 01.02.2026 as a number.
        assert check_personal_data(message) is None

    def test_a_number_valid_elsewhere_needs_the_right_region(self):
        # The same digits are a landline in one plan and nothing in another.
        italian_landline = "Chiamatemi allo 050 509111"

        assert check_personal_data(italian_landline, phone_region="IT") == (
            VERDICT_PERSONAL_DATA
        )
        assert check_personal_data(italian_landline, phone_region="US") is None

    def test_an_unknown_region_finds_nothing_instead_of_raising(self):
        # A mistyped region must not break every message. The settings model
        # rejects the typo first; this is the second line of defence.
        assert check_personal_data("tel 050 509111", phone_region="ZZ") is None

    @pytest.mark.parametrize(
        "toggle, message",
        [
            ("detect_email", "scrivimi a mario.rossi@sns.it"),
            ("detect_codice_fiscale", f"CF {VALID_CODICE_FISCALE}"),
            ("detect_iban", f"IBAN {VALID_IBAN_IT}"),
            ("detect_phone", "chiamami al 3401234567"),
        ],
    )
    def test_each_detector_can_be_switched_off_on_its_own(self, toggle, message):
        assert check_personal_data(message, allowed_email=HELP_DESK) is not None
        assert check_personal_data(
            message, allowed_email=HELP_DESK, **{toggle: False}
        ) is None

    def test_all_detectors_off_disables_the_check(self):
        message = f"mario.rossi@sns.it {VALID_CODICE_FISCALE} {VALID_IBAN_IT} 3401234567"
        assert (
            check_personal_data(
                message,
                detect_email=False,
                detect_codice_fiscale=False,
                detect_iban=False,
                detect_phone=False,
            )
            is None
        )

    def test_lowercase_codice_fiscale_is_recognised(self):
        assert check_personal_data(
            f"il mio cf e {VALID_CODICE_FISCALE.lower()}"
        ) == VERDICT_PERSONAL_DATA


class TestPersonalDataScanCost:
    """Regression: the scan must stay linear in the length of the message.

    The length guard normally bounds the input, but it can be disabled from the
    admin panel, and then these patterns run on whatever arrives. An unbounded
    quantifier before the `@` of the email pattern used to make a 100.000
    character message cost thirteen seconds inside `fast_reply` — the hook that
    runs before retrieval, before generation, before anything.
    """

    def test_a_long_message_without_personal_data_is_scanned_quickly(self):
        # Deliberately adversarial: long, uniform, and never reaching an `@`.
        message = "a" * 200_000

        start = time.perf_counter()
        verdict = check_personal_data(message)
        elapsed = time.perf_counter() - start

        assert verdict is None
        # Two orders of magnitude above what a linear scan costs, so a slow
        # machine cannot make this flaky, while a quadratic pattern cannot pass.
        assert elapsed < 2.0, f"scan took {elapsed:.2f}s, pattern is not linear"

    def test_a_long_message_ending_in_an_address_is_still_caught(self):
        # The bounded quantifiers must not stop a real address from matching.
        message = "a" * 50_000 + " scrivimi a mario.rossi@sns.it"

        assert check_personal_data(message) == VERDICT_PERSONAL_DATA


class TestPhoneNumberTypes:
    def test_reports_the_kind_of_number_for_the_log(self):
        assert phone_number_types("Chiamatemi allo 050 509111") == ("fixed_line",)
        assert phone_number_types("Chiamatemi al 3401234567") == ("mobile",)

    def test_reports_nothing_when_there_is_no_number(self):
        assert phone_number_types("Come attivo la VPN?") == ()


class TestMatchedPersonalDataKinds:
    def test_reports_every_kind_it_finds(self):
        message = f"mario.rossi@sns.it, CF {VALID_CODICE_FISCALE}, tel 3401234567"

        assert matched_personal_data_kinds(message, allowed_email=HELP_DESK) == (
            "email",
            "codice_fiscale",
            "phone",
        )

    def test_reports_nothing_on_a_clean_message(self):
        assert matched_personal_data_kinds("Come attivo la VPN?") == ()


class TestRunInputChecks:
    def test_returns_none_when_every_check_passes(self):
        assert run_input_checks("How do I activate the VPN?", config()) is None

    def test_returns_the_verdict_of_the_failing_check(self):
        assert run_input_checks("a" * 1001, config()) == VERDICT_MESSAGE_TOO_LONG

    def test_finds_a_verdict_from_a_later_check(self):
        assert run_input_checks("scrivimi a mario.rossi@sns.it", config()) == (
            VERDICT_PERSONAL_DATA
        )

    def test_length_is_evaluated_before_personal_data(self):
        # The order is deliberate: the cheap bound runs first, so the pattern
        # scans always work on a string of known size.
        message = "mario.rossi@sns.it " + "a" * 200

        assert run_input_checks(message, config(max_message_chars=100)) == (
            VERDICT_MESSAGE_TOO_LONG
        )
        assert run_input_checks(message, config(max_message_chars=0)) == (
            VERDICT_PERSONAL_DATA
        )
