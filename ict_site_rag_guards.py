"""Guardrail pipeline for a website ICT support chatbot: Cheshire Cat hooks.

This module is the adapter between Cheshire Cat and the pure decision logic in
`checks.py`. It reads from the Cat, loads the configuration, delegates every
decision, and writes back. No threshold and no rule live here.

One hook: `fast_reply`, for verdicts that depend on the incoming message alone.

A second hook on `agent_fast_reply` existed and was removed. It was the dispatch
point for verdicts that can only be formed after the recall — the evidence gate
of Fase 3 — and that gate is not planned: refusing on an empty recall duplicates
an instruction the deployed prompt already carries, while refusing greetings and
follow-up questions. With no check producing a post-recall verdict, the hook
registered a behaviour the plugin does not have. If such a check ever arrives,
`agent_fast_reply` is still the only place it can reply from, and the reasoning
is in `DEV/AGENTS/PROJECT.md`, section *Why input checks run on `fast_reply`*.

Input checks run on `fast_reply`, the earliest hook, for two reasons that both
matter more than the single dispatch point the design document assumes:

1. It is the only place where a refused message never reaches the vector
   database. On the `agent_fast_reply` path the core still stores the user
   message in episodic memory after the agent returns, so a message blocked for
   containing personal data would be persisted anyway — and the embedding is
   computed from the original text, which `before_cat_stores_episodic_memory`
   cannot undo.
2. It makes the check independent of any other plugin. Hooks with the same name
   are piped, not short-circuited, in descending priority order, and the last
   non-None return wins. A negative priority puts this plugin last, so its reply
   is the one delivered whatever the `Rate Limiter` plugin decided. Its side
   effects, such as progressive suspensions, are outside this plugin's reach.

A refused message therefore also skips the retrieval, the conversation history
and `before_cat_sends_message`. That is intentional: there is nothing to filter
in a reply we wrote ourselves, and an over-long message is better left out of
the history.

Reference: DEV/TODO/Workflow_RAG_Cheshire_Cat_AI_semplificato_v12.docx, Fasi 1-2.
"""

import os
import time

from cat.log import log
from cat.mad_hatter.decorators import hook
from pydantic import ValidationError

# The Cat imports plugin files as `cat.plugins.<folder>.<module>`, which makes
# the relative import the correct one at runtime. The absolute fallback is what
# lets the tests import this module directly, with the plugin folder on the path.
try:
    from .checks import (
        CATEGORY_LIMITS,
        CATEGORY_PRIVACY,
        CATEGORY_SECURITY,
        STAGE_INPUT,
        VERDICT_MESSAGE_LENGTH,
        VERDICT_PERSONAL_DATA,
        VERDICT_PROMPT_INJECTION,
        category_of,
        extract_text,
        matched_personal_data_kinds,
        matched_prompt_injection_pattern,
        phone_number_types,
        run_input_checks,
        stage_of,
    )
    from .prompt_injection_classifier import (
        classifier_load_error,
        classify_prompt_injection,
    )
    from .settings import IctSiteRagGuardsSettings
except ImportError:  # pragma: no cover - depends on how the module is loaded
    from checks import (
        CATEGORY_LIMITS,
        CATEGORY_PRIVACY,
        CATEGORY_SECURITY,
        STAGE_INPUT,
        VERDICT_MESSAGE_LENGTH,
        VERDICT_PERSONAL_DATA,
        VERDICT_PROMPT_INJECTION,
        category_of,
        extract_text,
        matched_personal_data_kinds,
        matched_prompt_injection_pattern,
        phone_number_types,
        run_input_checks,
        stage_of,
    )
    from prompt_injection_classifier import (
        classifier_load_error,
        classify_prompt_injection,
    )
    from settings import IctSiteRagGuardsSettings

# Where the verdict of the turn is recorded. `WorkingMemory` allows extra
# attributes and lives for the whole session, so it is reset at the beginning of
# every turn — a stale verdict would otherwise describe the wrong message.
#
# Written and never read inside this plugin, deliberately: it used to be the
# carrier between two hooks, and it is now the trace the telemetry module will
# read instead of parsing log lines.
VERDICT_ATTRIBUTE = "ict_guard_verdict"

# Runs after every other plugin on `fast_reply`. The Rate Limiter plugin uses
# the default priority of 1, and core plugin hooks use 0; a negative value is
# unambiguously last, and being last is what makes this plugin's reply win.
INPUT_GUARD_PRIORITY = -1

# Which settings field holds the reply text of each verdict. Adding a check
# means adding an entry here and a field to the settings model; the tests fail
# if the two get out of step.
#
# The keys are verdicts and the values are settings field names, and the two
# namespaces are deliberately independent: a verdict may be renamed freely,
# because it is never persisted, while renaming a field silently discards the
# text an administrator edited in the admin panel. Two verdicts may also point
# at the same field, which is what Fase 3 and Fase 5 need when they share one
# insufficiency message.
REPLY_SETTING_BY_VERDICT = {
    VERDICT_MESSAGE_LENGTH: "message_too_long",
    VERDICT_PERSONAL_DATA: "personal_data_detected",
    VERDICT_PROMPT_INJECTION: "prompt_injection_detected",
}

# The guard configuration as it was last announced. A guard disabled from the
# admin panel leaves no other trace, and this plugin exists to prevent silent
# gaps, so the whole configuration is announced once and then only when it
# changes — not at every turn, which would be noise on every conversation.
_ANNOUNCED_GUARD_SUMMARY: str | None = None

# The classifier failure already reported. The classifier is fail-open, so a
# model that cannot load leaves the message unblocked on every turn — reporting
# it once per turn would bury the log without adding information, since the state
# cannot change until the plugin reloads.
_ANNOUNCED_CLASSIFIER_FAILURE: str | None = None


def load_settings(cat) -> IctSiteRagGuardsSettings:
    """Return the plugin configuration, falling back to the model defaults.

    Never raises. A configuration problem must not take the guard down, and
    falling back to the defaults keeps the checks running. It also lets the
    hooks be called with a fake `cat` that has no plugin registry at all.

    The fallback is not only defensive: `load_settings()` returns settings.json
    verbatim, so an empty or partial file would otherwise yield no values.
    """
    try:
        stored = cat.mad_hatter.get_plugin().load_settings()
    except Exception as error:
        log.debug(
            f"[ict-site-rag-guards] settings unavailable ({error}), using defaults"
        )
        return IctSiteRagGuardsSettings()

    try:
        return IctSiteRagGuardsSettings.model_validate(stored or {})
    except ValidationError as error:
        log.warning(
            f"[ict-site-rag-guards] invalid settings, using defaults: {error}"
        )
        return IctSiteRagGuardsSettings()


def _render(template: str, settings: IctSiteRagGuardsSettings) -> str:
    """Insert the configured values into a reply text.

    A plain replace, not str.format: the text is edited by hand in the admin
    panel, and any stray brace would make format() raise on a message that is
    only meant to be shown to a user.
    """
    return template.replace("{help_desk_email}", settings.help_desk_email)


def reply_for(verdict: str, settings: IctSiteRagGuardsSettings) -> str | None:
    """Return the configured reply for a verdict, or None if there is none.

    A verdict with no reply is a bug, not a valid state: the caller answers
    normally rather than sending an empty message, and logs the gap.
    """
    setting_name = REPLY_SETTING_BY_VERDICT.get(verdict)
    if setting_name is None:
        log.warning(
            f"[ict-site-rag-guards] no reply configured for verdict "
            f"'{verdict}', falling back to normal execution"
        )
        return None
    return _render(getattr(settings, setting_name), settings)


def enabled_privacy_detectors(
    settings: IctSiteRagGuardsSettings,
) -> tuple[str, ...]:
    """The personal-data detectors currently switched on."""
    return tuple(
        name
        for name, enabled in (
            ("email", settings.detect_email),
            ("codice_fiscale", settings.detect_codice_fiscale),
            ("iban", settings.detect_iban),
            ("phone", settings.detect_phone),
        )
        if enabled
    )


def enabled_check_names(settings: IctSiteRagGuardsSettings) -> tuple[str, ...]:
    """Which input checks are effectively active, in the order they run.

    A check whose configuration disables it — a non-positive length limit, all
    four privacy detectors off — is not listed, because it decides nothing.
    """
    names = []
    if settings.max_message_chars > 0:
        names.append("length")
    if settings.detect_prompt_injection_custom:
        names.append("injection_patterns")
    if enabled_privacy_detectors(settings):
        names.append("personal_data")
    if settings.detect_prompt_injection_classifier and not classifier_load_error(
        settings.prompt_injection_classifier_model.value
    ):
        # Last on purpose: it runs only when every deterministic check passed.
        # Enabled in the settings is not enough — a model that failed to load is
        # not covering anything, and listing it would make the line claim a
        # coverage the turn did not have.
        names.append("injection_classifier")
    return tuple(names)


def active_guards_summary(
    settings: IctSiteRagGuardsSettings,
) -> tuple[str, tuple[str, ...]]:
    """The guard configuration as one line, plus the categories left uncovered.

    One string per category, so the line reads as the answer to «what is
    actually protecting this instance» — the question the admin form answers
    only by being opened, field by field.
    """
    if settings.max_message_chars > 0:
        limits = f"{CATEGORY_LIMITS}(max {settings.max_message_chars} chars)"
    else:
        limits = f"{CATEGORY_LIMITS}(disabled)"

    detectors = enabled_privacy_detectors(settings)
    if detectors:
        privacy = (
            f"{CATEGORY_PRIVACY}({'+'.join(detectors)}, "
            f"region={settings.phone_region})"
        )
    else:
        privacy = f"{CATEGORY_PRIVACY}(disabled)"

    mechanisms = []
    if settings.detect_prompt_injection_custom:
        mechanisms.append("patterns")
    if settings.detect_prompt_injection_classifier:
        mechanisms.append(
            f"classifier {settings.prompt_injection_classifier_model.value}"
            f"@{settings.prompt_injection_classifier_threshold:.2f}"
        )
    if mechanisms:
        security = f"{CATEGORY_SECURITY}({'+'.join(mechanisms)})"
    else:
        security = f"{CATEGORY_SECURITY}(disabled)"

    uncovered = tuple(
        category
        for category, description in (
            (CATEGORY_LIMITS, limits),
            (CATEGORY_PRIVACY, privacy),
            (CATEGORY_SECURITY, security),
        )
        if description.endswith("(disabled)")
    )

    return f"{limits}, {privacy}, {security}", uncovered


def announce_active_guards(settings: IctSiteRagGuardsSettings) -> None:
    """Log the guard configuration once, and again whenever it changes.

    Not at every turn: on a message that passes, the plugin writes nothing at
    `INFO`, and that silence used to be indistinguishable from the plugin not
    running at all. This line is what tells the two apart. Announced on change
    rather than per message so the cost stays at one tuple comparison and the
    log of a normal conversation stays readable.

    A category with nothing left enabled is a `WARNING`, because that is the
    state where the chatbot is unguarded and nothing else says so.
    """
    global _ANNOUNCED_GUARD_SUMMARY

    summary, uncovered = active_guards_summary(settings)
    if summary == _ANNOUNCED_GUARD_SUMMARY:
        return

    if uncovered:
        log.warning(
            f"[ict-site-rag-guards] guards active: {summary}; "
            f"no guard covers: {', '.join(uncovered)}"
        )
    else:
        log.info(f"[ict-site-rag-guards] guards active: {summary}")

    _ANNOUNCED_GUARD_SUMMARY = summary


def blocked_detail(
    verdict: str, text: str, settings: IctSiteRagGuardsSettings
) -> str:
    """Context for the log line, never the message itself.

    The refused text must not reach the logs: on the personal-data verdict that
    would defeat the point of the check. Only the shape of the violation is
    recorded — how long the message was, or which detector fired.
    """
    if verdict == VERDICT_MESSAGE_LENGTH:
        return f", length={len(text)} chars (limit {settings.max_message_chars})"

    if verdict == VERDICT_PERSONAL_DATA:
        kinds = matched_personal_data_kinds(
            text,
            detect_email=settings.detect_email,
            detect_codice_fiscale=settings.detect_codice_fiscale,
            detect_iban=settings.detect_iban,
            detect_phone=settings.detect_phone,
            allowed_email=settings.help_desk_email,
            phone_region=settings.phone_region,
        )
        detail = f", detected={'+'.join(kinds)}"

        # The kind of number is useful to whoever reads the logs, and is not a
        # setting: see the note on `phone_number_types`.
        if "phone" in kinds:
            types = phone_number_types(text, settings.phone_region)
            detail += f" ({'+'.join(sorted(set(types)))})"

        return detail

    if verdict == VERDICT_PROMPT_INJECTION:
        # Only the pattern detector reaches this function: the classifier path
        # builds its own detail, because it has a score and a latency to report.
        pattern = matched_prompt_injection_pattern(
            text, settings.detect_prompt_injection_custom
        )
        if pattern is None:  # pragma: no cover - defensive, the check just fired
            return ", detector=custom"
        return f", detector=custom, pattern={pattern}"

    return ""


def announce_classifier_failure(
    error: Exception, settings: IctSiteRagGuardsSettings
) -> None:
    """Report a fail-open classifier once, naming what still covers the turn.

    Once per failure rather than once per message: the classifier cannot recover
    without the plugin reloading, so the state is constant and repeating it every
    turn buries the log exactly when a configuration problem needs diagnosing.

    What the line must say is *what is left*, because the announcement of the
    active guards was built from the settings and therefore claimed a classifier
    that turns out not to run. When the built-in patterns are off as well, this is
    the only line saying the security category covers nothing.
    """
    global _ANNOUNCED_CLASSIFIER_FAILURE

    reported = f"{settings.prompt_injection_classifier_model.value}: {error}"
    if reported == _ANNOUNCED_CLASSIFIER_FAILURE:
        return
    _ANNOUNCED_CLASSIFIER_FAILURE = reported

    if settings.detect_prompt_injection_custom:
        remaining = (
            f"the {CATEGORY_SECURITY} guard continues on its built-in patterns only"
        )
    else:
        remaining = (
            f"no guard covers: {CATEGORY_SECURITY} — the built-in patterns are "
            "disabled too"
        )

    log.warning(
        f"[ict-site-rag-guards] prompt-injection classifier unavailable "
        f"({reported}), continuing without blocking; {remaining}. "
        "Not repeated until the plugin reloads"
    )


def detect_prompt_injection_with_classifier(
    text: str, settings: IctSiteRagGuardsSettings
) -> dict[str, str | float] | None:
    """Run the local prompt-injection classifier, fail-open on any error."""
    if not settings.detect_prompt_injection_classifier:
        return None

    model_name = settings.prompt_injection_classifier_model.value
    token = resolve_huggingface_token(settings)

    started = time.perf_counter()
    try:
        result = classify_prompt_injection(
            text,
            model_name=model_name,
            threshold=settings.prompt_injection_classifier_threshold,
            max_length=settings.max_message_chars,
            token=token,
        )
    except Exception as error:
        announce_classifier_failure(error, settings)
        return None

    elapsed_ms = (time.perf_counter() - started) * 1000
    if not result["triggered"]:
        return None

    return {
        "detail": (
            ", detector=classifier"
            f", model={model_name}"
            f", label={result['label']}"
            f", score={result['score']:.3f}"
            f", threshold={settings.prompt_injection_classifier_threshold:.2f}"
            f", latency_ms={elapsed_ms:.1f}"
        ),
    }


def resolve_huggingface_token(settings: IctSiteRagGuardsSettings) -> str | None:
    """Return the Hugging Face token to use for gated models, if any.

    Environment variables take precedence over admin settings so deployments can
    keep secrets out of the plugin configuration when they want to.
    """
    token = os.getenv("HF_TOKEN", "").strip()
    if token:
        return token

    token = settings.huggingface_token.strip()
    return token or None


@hook("fast_reply", priority=INPUT_GUARD_PRIORITY)
def guard_input_message(fast_reply, cat):
    """Run the input checks and answer immediately when one of them trips.

    Returning a dict containing an "output" key is what makes the core return
    straight away, before retrieval, before the agent, and before the message is
    stored in episodic memory. Returning the received dict untouched lets the
    flow continue — and preserves a reply another plugin may have already put
    there, so a rate-limit block from `Rate Limiter` still reaches the user.

    No generative call happens here: the checks are deterministic and cost
    computation, not tokens.
    """
    # The span covers everything this hook costs the turn, settings included:
    # the first message after an activation also pays the classifier model load,
    # and that is worth seeing rather than hiding.
    started = time.perf_counter()

    # Reset any verdict from the previous turn: working memory lives for the
    # whole session, and this is the earliest hook of the turn.
    setattr(cat.working_memory, VERDICT_ATTRIBUTE, None)

    settings = load_settings(cat)
    announce_active_guards(settings)

    text = extract_text(getattr(cat.working_memory, "user_message_json", None))
    verdict = run_input_checks(text, settings)
    detail = blocked_detail(verdict, text, settings) if verdict is not None else ""

    if verdict is None:
        classifier_result = detect_prompt_injection_with_classifier(text, settings)
        if classifier_result is not None:
            verdict = VERDICT_PROMPT_INJECTION
            detail = classifier_result["detail"]

    elapsed_ms = (time.perf_counter() - started) * 1000

    if verdict is None:
        # DEBUG, not INFO: one line per message would be noise on every normal
        # conversation, and the announcement above already proves the guards are
        # running. This is for diagnosing one specific message, where `checks=`
        # is the answer to whether the turn was covered and by what.
        # Two decimals, not one: the deterministic checks cost hundredths of a
        # millisecond, and `latency_ms=0.0` reads as a broken timer rather than
        # as a fast path. The classifier, when it runs, is three orders of
        # magnitude above that and stays readable either way.
        log.debug(
            f"[ict-site-rag-guards] input allowed, "
            f"stage='{STAGE_INPUT}', "
            f"checks={'+'.join(enabled_check_names(settings)) or 'none'}, "
            f"latency_ms={elapsed_ms:.2f}"
        )
        return fast_reply

    reply = reply_for(verdict, settings)
    if reply is None:
        return fast_reply

    # This hook answers on its own, so nothing in this plugin reads the verdict
    # back. It is kept as the trace of why the turn was refused, for the future
    # telemetry module and for anything else inspecting working memory: unlike a
    # hook registration, an attribute claims no behaviour the plugin lacks.
    setattr(cat.working_memory, VERDICT_ATTRIBUTE, verdict)

    log.info(
        f"[ict-site-rag-guards] input blocked, "
        f"stage='{stage_of(verdict)}', "
        f"category='{category_of(verdict)}', verdict='{verdict}'"
        f"{detail}, latency_ms={elapsed_ms:.2f}; "
        f"no retrieval, no generation, nothing stored in memory"
    )
    return {"output": reply}
