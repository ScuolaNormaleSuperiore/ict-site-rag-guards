"""Pure decision logic of the guardrail pipeline.

This module must never import anything from `cat`. It works only on plain
strings and numbers, so it can be exercised with pytest alone: no running
Cheshire Cat instance, no container, and none of the core dependencies
installed.

Every check follows the same contract:

    check_<name>(text, <configuration>) -> str | None

It returns the name of a verdict when the message must be stopped, or None
when the message passes. Mapping a verdict to the text sent to the user is not
this module's job: it belongs to the hooks in `ict_site_rag_guards.py`.

Keeping this signature uniform across checks is what will later allow the
checks to be iterated over, enabled or reordered from configuration without
rewriting them.

Reference: DEV/TODO/Workflow_RAG_Cheshire_Cat_AI_semplificato_v12.docx, Fasi 2, 5.
"""

import re
from typing import Any, Mapping

import phonenumbers
from phonenumbers import Leniency, PhoneNumberMatcher, PhoneNumberType

# Verdict names, shared with the hooks module: a rename here cannot silently
# break the link between a check and the reply it is supposed to trigger.
#
# A verdict names the control that tripped, not the family it belongs to, and
# that is deliberate: the verdict is also the key of the reply sent to the user,
# so one verdict per control is what lets a refusal say what to correct. A
# generic verdict would force one vague text on every control of its family.
# The family is the category below.
VERDICT_MESSAGE_LENGTH = "message_length"
VERDICT_PERSONAL_DATA = "personal_data"
VERDICT_OUTPUT_PERSONAL_DATA = "output_personal_data"
VERDICT_PROMPT_INJECTION = "prompt_injection"

# The single source for which verdicts exist. Tests derive from this instead of
# introspecting the module for a name prefix, which would keep passing on an
# empty set the moment the naming convention changed.
ALL_VERDICTS = (
    VERDICT_MESSAGE_LENGTH,
    VERDICT_PERSONAL_DATA,
    VERDICT_OUTPUT_PERSONAL_DATA,
    VERDICT_PROMPT_INJECTION,
)

# Where a guard acts in the pipeline. Only `input` is implemented today, but
# the taxonomy is explicit already so output and retrieval checks can reuse the
# same log and telemetry shape instead of inventing a second one later.
STAGE_INPUT = "input"
STAGE_OUTPUT = "output"
STAGE_RETRIEVAL = "retrieval"
STAGE_SESSION = "session"

# Why a request was refused, as opposed to which control refused it. Three axes
# coexist here and each answers one question: the stage says *where* a guard
# runs, the verdict says *what* tripped, the category says *why*. Keeping them
# separate is what makes "how many privacy refusals this week" answerable from
# the logs without parsing verdict names, while leaving each control free to
# keep its own reply text.
CATEGORY_LIMITS = "limits"
CATEGORY_PRIVACY = "privacy"
CATEGORY_SECURITY = "security"

STAGE_BY_VERDICT = {
    VERDICT_MESSAGE_LENGTH: STAGE_INPUT,
    VERDICT_PERSONAL_DATA: STAGE_INPUT,
    VERDICT_OUTPUT_PERSONAL_DATA: STAGE_OUTPUT,
    VERDICT_PROMPT_INJECTION: STAGE_INPUT,
}

# Every verdict has one, including those set outside this module: the classifier
# path in the hooks today, the evidence gate and the output checks later. A test
# enforces it, because a verdict with no category does not fail anything — it
# just disappears from the telemetry.
CATEGORY_BY_VERDICT = {
    VERDICT_MESSAGE_LENGTH: CATEGORY_LIMITS,
    VERDICT_PERSONAL_DATA: CATEGORY_PRIVACY,
    VERDICT_OUTPUT_PERSONAL_DATA: CATEGORY_PRIVACY,
    VERDICT_PROMPT_INJECTION: CATEGORY_SECURITY,
}

# What an unclassified verdict is reported as. Not an exception: a gap in the
# taxonomy has no effect on the user, so it must not be able to take down the
# hook that runs before everything else. The test is what prevents it.
UNCATEGORIZED = "uncategorized"
UNKNOWN_STAGE = "unknown"

# Maximum accepted length of a user message, in characters. Starting value:
# high enough not to hinder an articulated question, low enough to stop a
# pasted document. Kept below the Rate Limiter plugin's own `max_prompt_length`
# so that this plugin, and not that one, answers an over-long message.
DEFAULT_MAX_MESSAGE_CHARS = 1000
DEFAULT_PROMPT_INJECTION_CLASSIFIER_THRESHOLD = 0.85

# The v1 custom detector is deliberately conservative: high-precision phrases
# that directly try to alter the assistant's rules or reveal its hidden
# instructions. The classifier covers the broader grey area.
#
# Each pattern carries a name, and the name reaches the log. Six anonymous
# regexes produce one indistinguishable log line, which is exactly what makes a
# false positive impossible to diagnose: the refused text is deliberately not
# logged, so without the pattern name there is nothing left to reason from.
# Names are part of the log contract — treat a rename as a breaking change for
# whoever greps these lines.
_PROMPT_INJECTION_PATTERNS = (
    (
        "override_instructions_en",
        re.compile(
            r"\b(?:ignore|disregard|forget|override|bypass)\b.{0,40}\b"
            r"(?:instructions|rules|guardrails|safety|system prompt|prompt)\b"
        ),
    ),
    (
        "reveal_prompt_en",
        re.compile(
            r"\b(?:reveal|show|display|print|tell me)\b.{0,40}\b"
            r"(?:system prompt|hidden prompt|developer instructions|internal instructions)\b"
        ),
    ),
    (
        "jailbreak_mode_en",
        re.compile(r"\b(?:developer mode|jailbreak|do anything now)\b"),
    ),
    (
        "override_instructions_it",
        re.compile(
            r"\b(?:ignora|disattiva|scavalca|aggira|sovrascrivi)\b.{0,40}\b"
            r"(?:istruzioni|regole|guardrail|vincoli|prompt di sistema|prompt)\b"
        ),
    ),
    (
        "reveal_prompt_it",
        re.compile(
            r"\b(?:rivela|mostra|stampa|dimmi)\b.{0,40}\b"
            r"(?:prompt di sistema|prompt nascosto|istruzioni sviluppatore|istruzioni interne)\b"
        ),
    ),
    (
        "jailbreak_mode_it",
        re.compile(r"\b(?:modalita sviluppatore|modalità sviluppatore)\b"),
    ),
)

# --- Personal data patterns -------------------------------------------------
#
# Two of these are only candidate finders: a codice fiscale and an IBAN carry a
# check character, verified below, which turns "looks like one" into "is one".
# That is what keeps the false-positive rate at essentially zero without any
# third-party dependency.

# Every quantifier here is bounded, and that is not cosmetic. With an open `+`
# on each side of the `@`, a long run of matching characters that never reaches
# an `@` makes the engine retry at every starting position: a 100.000-character
# message cost thirteen seconds of CPU inside `fast_reply`, which is a denial of
# service on the hook that runs before everything else. The bounds are the ones
# RFC 5321 already imposes on a mailbox, so no legitimate address stops matching.
_EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,255}\.[A-Za-z]{2,24}"
)

# Six letters, two year digits, a month letter, two day digits, the four
# characters of the place code, and the check character. Sixteen in total.
_CODICE_FISCALE_PATTERN = re.compile(
    r"\b[A-Za-z]{6}\d{2}[ABCDEHLMPRSTabcdehlmprst]\d{2}[A-Za-z]\d{3}[A-Za-z]\b"
)

# Country code, two check digits, then the national part.
_IBAN_PATTERN = re.compile(r"\b[A-Za-z]{2}\d{2}[A-Za-z0-9]{11,30}\b")

# Region assumed for numbers written without an international prefix. A number
# is only valid relative to a numbering plan, so this has to be configurable:
# the same digits are a landline in one country and nothing in another.
DEFAULT_PHONE_REGION = "IT"

# Phone numbers are the one case here where a library beats our own patterns,
# and the reason is worth keeping in mind: the check character of a codice
# fiscale and the mod-97 of an IBAN are frozen algorithms, so nothing is gained
# by depending on someone else's code, while a numbering plan is external data
# that changes — new prefixes, lengths that grow.
#
# STRICT_GROUPING is the leniency that earns its keep. Measured on realistic
# help-desk messages: it finds every landline and mobile, and rejects dates
# written as 01.02.2026 or 01-02-2026, which the looser VALID accepts as
# numbers. EXACT_GROUPING is stricter still and starts missing real numbers
# written as "06 1234567".
_PHONE_LENIENCY = Leniency.STRICT_GROUPING

# Built from the library's own constants so it cannot drift out of step.
_PHONE_TYPE_NAMES = {
    getattr(PhoneNumberType, name): name.lower()
    for name in dir(PhoneNumberType)
    if name.isupper()
}

# Value of each character in an odd position of a codice fiscale, counting from
# one. Even positions use the plain alphabet index, so they need no table.
_CODICE_FISCALE_ODD_VALUES = {
    "0": 1, "1": 0, "2": 5, "3": 7, "4": 9,
    "5": 13, "6": 15, "7": 17, "8": 19, "9": 21,
    "A": 1, "B": 0, "C": 5, "D": 7, "E": 9,
    "F": 13, "G": 15, "H": 17, "I": 19, "J": 21,
    "K": 2, "L": 4, "M": 18, "N": 20, "O": 11,
    "P": 3, "Q": 6, "R": 8, "S": 12, "T": 14,
    "U": 16, "V": 10, "W": 22, "X": 25, "Y": 24, "Z": 23,
}


def extract_text(message: Any) -> str:
    """Return the text of an incoming or outgoing message.

    Accepts either a mapping or any object exposing a `text` attribute: the
    core type hints declare dicts for some hooks, but the live flow also passes
    message objects such as `UserMessage` and `CatMessage`. Duck typing keeps
    this module free of imports from `cat`.
    """
    if isinstance(message, Mapping):
        return message.get("text") or message.get("content") or ""
    return getattr(message, "text", "") or getattr(message, "content", "") or ""


def category_of(verdict: str) -> str:
    """Return the family a verdict belongs to, for the log and the telemetry."""
    return CATEGORY_BY_VERDICT.get(verdict, UNCATEGORIZED)


def stage_of(verdict: str) -> str:
    """Return where in the pipeline a verdict was produced."""
    return STAGE_BY_VERDICT.get(verdict, UNKNOWN_STAGE)


def check_length(
    text: str, max_chars: int = DEFAULT_MAX_MESSAGE_CHARS
) -> str | None:
    """Stop messages longer than `max_chars` characters.

    A non-positive `max_chars` disables the check, the same convention the
    Rate Limiter plugin uses for its own length limit.
    """
    if max_chars <= 0:
        return None
    if len(text) > max_chars:
        return VERDICT_MESSAGE_LENGTH
    return None


def _normalize_for_prompt_injection(text: str) -> str:
    """Normalize free text for the conservative custom detector.

    The detector is phrase-based, not token-model based, so only cheap and
    predictable normalization belongs here: lowercase and whitespace collapse.
    """
    return " ".join(text.casefold().split())


def matched_prompt_injection_pattern(
    text: str, enabled: bool = True
) -> str | None:
    """Return the name of the first pattern that matches, for logging.

    The counterpart of `matched_personal_data_kinds`, and there for the same
    reason: the verdict tells the user's reply apart, the name tells whoever
    reads the log which of the six phrases fired. Only the name is returned,
    never the matched text, which would put the refused message in the log.
    """
    if not enabled:
        return None

    normalized = _normalize_for_prompt_injection(text)
    if not normalized:
        return None

    for name, pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(normalized):
            return name

    return None


def check_prompt_injection(text: str, enabled: bool = True) -> str | None:
    """Stop explicit prompt-injection attempts with a conservative pattern set."""
    if matched_prompt_injection_pattern(text, enabled) is not None:
        return VERDICT_PROMPT_INJECTION
    return None


def _is_valid_codice_fiscale(candidate: str) -> bool:
    """Verify the check character of a sixteen-character codice fiscale.

    Odd positions, counting from one, are weighted through a table; even ones
    use the plain alphabet index. The sum modulo 26 gives the final letter.
    """
    candidate = candidate.upper()
    if len(candidate) != 16:
        return False

    total = 0
    for index, character in enumerate(candidate[:15], start=1):
        if index % 2 == 1:
            value = _CODICE_FISCALE_ODD_VALUES.get(character)
            if value is None:
                return False
            total += value
        elif character.isdigit():
            total += int(character)
        else:
            total += ord(character) - ord("A")

    return candidate[15] == chr(ord("A") + total % 26)


def _is_valid_iban(candidate: str) -> bool:
    """Verify an IBAN with the mod-97 check defined by ISO 13616.

    The first four characters move to the end, letters become numbers, and the
    resulting integer must leave a remainder of one when divided by 97.
    """
    candidate = candidate.upper()
    if not 15 <= len(candidate) <= 34:
        return False

    rearranged = candidate[4:] + candidate[:4]
    digits = ""
    for character in rearranged:
        if character.isdigit():
            digits += character
        elif character.isalpha():
            digits += str(ord(character) - ord("A") + 10)
        else:
            return False

    return int(digits) % 97 == 1


def found_phone_numbers(
    text: str, region: str = DEFAULT_PHONE_REGION
) -> tuple[str, ...]:
    """Phone numbers in free text that the numbering plan of `region` accepts.

    An unknown region yields no matches rather than an error, which is the
    library's own behaviour and the one we want: a mistyped region must not
    break every message. The settings model validates the shape as well.
    """
    return tuple(
        match.raw_string
        for match in PhoneNumberMatcher(text, region, leniency=_PHONE_LENIENCY)
    )


def phone_number_types(
    text: str, region: str = DEFAULT_PHONE_REGION
) -> tuple[str, ...]:
    """Kinds of number found — `fixed_line`, `mobile` — for the log only.

    Deliberately not a setting: the distinction is useful to whoever reads the
    logs, and useless as a control. Landline against mobile is a technical
    category, while the privacy question is published against personal, and a
    home landline falls on the wrong side of that mapping.
    """
    return tuple(
        _PHONE_TYPE_NAMES.get(phonenumbers.number_type(match.number), "unknown")
        for match in PhoneNumberMatcher(text, region, leniency=_PHONE_LENIENCY)
    )


def matched_personal_data_kinds(
    text: str,
    detect_email: bool = True,
    detect_codice_fiscale: bool = True,
    detect_iban: bool = True,
    detect_phone: bool = True,
    allowed_email: str = "",
    phone_region: str = DEFAULT_PHONE_REGION,
) -> tuple[str, ...]:
    """Return the names of the detectors that match, for logging.

    The user is told only that the message contains personal data; which kind
    is the plugin's business, not theirs. This exists so the log can say which
    detector fired without the caller running the patterns a second time in a
    different way.
    """
    matched = []

    if detect_email:
        allowed = allowed_email.strip().lower()
        found = _EMAIL_PATTERN.findall(text)
        # The configured Help Desk address is not personal data: a user writing
        # "I already emailed helpdesk@..." must not be refused.
        if any(address.lower() != allowed for address in found):
            matched.append("email")

    if detect_codice_fiscale and any(
        _is_valid_codice_fiscale(candidate)
        for candidate in _CODICE_FISCALE_PATTERN.findall(text)
    ):
        matched.append("codice_fiscale")

    if detect_iban and any(
        _is_valid_iban(candidate) for candidate in _IBAN_PATTERN.findall(text)
    ):
        matched.append("iban")

    if detect_phone and found_phone_numbers(text, phone_region):
        matched.append("phone")

    return tuple(matched)


def _check_personal_data_with_verdict(
    text: str,
    verdict: str,
    detect_email: bool = True,
    detect_codice_fiscale: bool = True,
    detect_iban: bool = True,
    detect_phone: bool = True,
    allowed_email: str = "",
    phone_region: str = DEFAULT_PHONE_REGION,
) -> str | None:
    """Stop text carrying personal data, returning the caller's verdict.

    Every detector can be switched off independently from the admin panel, so
    an installation can match its own sensitivity. All four off disables the
    check, the same way a non-positive length limit disables that one.
    """
    if matched_personal_data_kinds(
        text,
        detect_email=detect_email,
        detect_codice_fiscale=detect_codice_fiscale,
        detect_iban=detect_iban,
        detect_phone=detect_phone,
        allowed_email=allowed_email,
        phone_region=phone_region,
    ):
        return verdict
    return None


def check_personal_data(
    text: str,
    detect_email: bool = True,
    detect_codice_fiscale: bool = True,
    detect_iban: bool = True,
    detect_phone: bool = True,
    allowed_email: str = "",
    phone_region: str = DEFAULT_PHONE_REGION,
) -> str | None:
    """Stop incoming messages carrying personal data."""
    return _check_personal_data_with_verdict(
        text,
        VERDICT_PERSONAL_DATA,
        detect_email=detect_email,
        detect_codice_fiscale=detect_codice_fiscale,
        detect_iban=detect_iban,
        detect_phone=detect_phone,
        allowed_email=allowed_email,
        phone_region=phone_region,
    )


def check_output_personal_data(
    text: str,
    detect_email: bool = True,
    detect_codice_fiscale: bool = True,
    detect_iban: bool = True,
    detect_phone: bool = True,
    allowed_email: str = "",
    phone_region: str = DEFAULT_PHONE_REGION,
) -> str | None:
    """Stop outgoing answers carrying personal data."""
    return _check_personal_data_with_verdict(
        text,
        VERDICT_OUTPUT_PERSONAL_DATA,
        detect_email=detect_email,
        detect_codice_fiscale=detect_codice_fiscale,
        detect_iban=detect_iban,
        detect_phone=detect_phone,
        allowed_email=allowed_email,
        phone_region=phone_region,
    )


def _run_length_check(text: str, config: Any) -> str | None:
    return check_length(text, config.max_message_chars)


def _run_prompt_injection_check(text: str, config: Any) -> str | None:
    return check_prompt_injection(text, config.detect_prompt_injection_custom)


def _run_personal_data_check(text: str, config: Any) -> str | None:
    return check_personal_data(
        text,
        detect_email=config.detect_input_email,
        detect_codice_fiscale=config.detect_input_codice_fiscale,
        detect_iban=config.detect_input_iban,
        detect_phone=config.detect_input_phone,
        allowed_email=config.help_desk_email,
        phone_region=config.input_phone_region,
    )


# The order is the policy, not an accident: the cheap bound runs first, so the
# pattern scans always work on a string of known size. Adding a check means
# adding its adapter here and its reply mapping in the hooks module.
INPUT_CHECKS = (
    _run_length_check,
    _run_prompt_injection_check,
    _run_personal_data_check,
)


def run_input_checks(text: str, config: Any) -> str | None:
    """Run every input check in order and return the first verdict found.

    `config` is anything exposing the settings fields the checks read, which
    keeps this module free of imports from `cat`: the hooks pass the settings
    model, the tests pass a namespace.
    """
    for check in INPUT_CHECKS:
        verdict = check(text, config)
        if verdict is not None:
            return verdict
    return None
