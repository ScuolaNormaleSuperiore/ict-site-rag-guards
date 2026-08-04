"""Guardrail pipeline for a website ICT support chatbot: Cheshire Cat hooks.

This module is the adapter between Cheshire Cat and the pure decision logic in
`checks.py`. It reads from the Cat, loads the configuration, delegates every
decision, and writes back. No threshold and no rule live here.

Two hooks, at two different points of the flow:

    fast_reply       -> verdicts that depend on the incoming message alone
    agent_fast_reply -> verdicts that can only be formed after the recall

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

Reference: DEV/TODO/Workflow_RAG_Cheshire_Cat_AI_semplificato_v12.docx, Fasi 1-3.
"""

from cat.log import log
from cat.mad_hatter.decorators import hook
from pydantic import ValidationError

# The Cat imports plugin files as `cat.plugins.<folder>.<module>`, which makes
# the relative import the correct one at runtime. The absolute fallback is what
# lets the tests import this module directly, with the plugin folder on the path.
try:
    from .checks import (
        VERDICT_MESSAGE_TOO_LONG,
        VERDICT_PERSONAL_DATA,
        extract_text,
        matched_personal_data_kinds,
        phone_number_types,
        run_input_checks,
    )
    from .settings import IctSiteRagGuardsSettings
except ImportError:  # pragma: no cover - depends on how the module is loaded
    from checks import (
        VERDICT_MESSAGE_TOO_LONG,
        VERDICT_PERSONAL_DATA,
        extract_text,
        matched_personal_data_kinds,
        phone_number_types,
        run_input_checks,
    )
    from settings import IctSiteRagGuardsSettings

# Attribute used to carry a verdict across hooks within the same turn.
# `WorkingMemory` allows extra attributes and lives for the whole session, so
# the verdict is always reset at the beginning of each turn.
VERDICT_ATTRIBUTE = "ict_guard_verdict"

# Runs after every other plugin on `fast_reply`. The Rate Limiter plugin uses
# the default priority of 1, and core plugin hooks use 0; a negative value is
# unambiguously last, and being last is what makes this plugin's reply win.
INPUT_GUARD_PRIORITY = -1

# Which settings field holds the reply text of each verdict. Adding a check
# means adding an entry here and a field to the settings model; the tests fail
# if the two get out of step.
REPLY_SETTING_BY_VERDICT = {
    VERDICT_MESSAGE_TOO_LONG: "message_too_long",
    VERDICT_PERSONAL_DATA: "personal_data_detected",
}

# Which personal-data detectors were switched off the last time we looked. A
# detector disabled from the admin panel leaves no other trace, and this plugin
# exists to prevent silent gaps, so a change is announced in the log once
# instead of at every turn.
_ANNOUNCED_DISABLED_DETECTORS: tuple[str, ...] | None = None


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


def announce_disabled_detectors(settings: IctSiteRagGuardsSettings) -> None:
    """Log the personal-data detectors that are switched off, when that changes.

    Four independent toggles are four ways to disable a privacy control without
    leaving a trace anywhere. This is the only place that state becomes visible
    without opening the admin form.
    """
    global _ANNOUNCED_DISABLED_DETECTORS

    disabled = tuple(
        name
        for name, enabled in (
            ("email", settings.detect_email),
            ("codice_fiscale", settings.detect_codice_fiscale),
            ("iban", settings.detect_iban),
            ("phone", settings.detect_phone),
        )
        if not enabled
    )

    if disabled == _ANNOUNCED_DISABLED_DETECTORS:
        return

    if disabled:
        log.warning(
            f"[ict-site-rag-guards] personal-data detectors disabled: "
            f"{', '.join(disabled)}"
        )
    else:
        log.info("[ict-site-rag-guards] all personal-data detectors enabled")

    _ANNOUNCED_DISABLED_DETECTORS = disabled


def blocked_detail(
    verdict: str, text: str, settings: IctSiteRagGuardsSettings
) -> str:
    """Context for the log line, never the message itself.

    The refused text must not reach the logs: on the personal-data verdict that
    would defeat the point of the check. Only the shape of the violation is
    recorded — how long the message was, or which detector fired.
    """
    if verdict == VERDICT_MESSAGE_TOO_LONG:
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

    return ""


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
    # Reset any verdict from the previous turn: working memory lives for the
    # whole session, and this is the earliest hook of the turn.
    setattr(cat.working_memory, VERDICT_ATTRIBUTE, None)

    settings = load_settings(cat)
    announce_disabled_detectors(settings)

    text = extract_text(getattr(cat.working_memory, "user_message_json", None))
    verdict = run_input_checks(text, settings)

    if verdict is None:
        return fast_reply

    reply = reply_for(verdict, settings)
    if reply is None:
        return fast_reply

    # Recorded even though this hook answers on its own: it is the trace of why
    # the turn was refused, for the logs and for the future telemetry module.
    setattr(cat.working_memory, VERDICT_ATTRIBUTE, verdict)

    log.info(
        f"[ict-site-rag-guards] input blocked, verdict='{verdict}'"
        f"{blocked_detail(verdict, text, settings)}; "
        f"no retrieval, no generation, nothing stored in memory"
    )
    return {"output": reply}


@hook("agent_fast_reply", priority=1)
def dispatch_fast_reply(fast_reply, cat):
    """Answer with a static reply when a guard set a verdict after the recall.

    This is the dispatch point for checks that need the retrieved memories to
    decide, the evidence gate of Fase 3 above all. Unlike `fast_reply`, a reply
    returned here still goes through `before_cat_sends_message` and is recorded
    in the conversation history.
    """
    verdict = getattr(cat.working_memory, VERDICT_ATTRIBUTE, None)

    if verdict is None:
        return fast_reply

    reply = reply_for(verdict, load_settings(cat))
    if reply is None:
        return fast_reply

    log.info(
        f"[ict-site-rag-guards] static reply sent for verdict '{verdict}', "
        f"main agent skipped, zero generation tokens spent"
    )
    return {"output": reply}
