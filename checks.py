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

Reference: DEV/TODO/Workflow_RAG_Cheshire_Cat_AI_semplificato_v12.docx, Fase 2.
"""

from typing import Any, Mapping

# Verdict names, shared with the hooks module: a rename here cannot silently
# break the link between a check and the reply it is supposed to trigger.
VERDICT_MESSAGE_TOO_LONG = "message_too_long"

# Maximum accepted length of a user message, in characters. Starting value:
# high enough not to hinder an articulated question, low enough to stop a
# pasted document. Kept below the Rate Limiter plugin's own `max_prompt_length`
# so that this plugin, and not that one, answers an over-long message.
DEFAULT_MAX_MESSAGE_CHARS = 1000


def extract_text(user_message: Any) -> str:
    """Return the text of an incoming message.

    Accepts either a mapping or any object exposing a `text` attribute: the
    core type hints declare a dict but a `UserMessage` is what actually gets
    passed. Duck typing keeps this module free of imports from `cat`.
    """
    if isinstance(user_message, Mapping):
        return user_message.get("text") or ""
    return getattr(user_message, "text", "") or ""


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
        return VERDICT_MESSAGE_TOO_LONG
    return None


def run_input_checks(
    text: str, max_chars: int = DEFAULT_MAX_MESSAGE_CHARS
) -> str | None:
    """Run every input check in order and return the first verdict found.

    Currently a single check. It exists as a seam: further Fase 2 checks
    (personal data, language, offensiveness, injection) are added here, and the
    hook above keeps calling one function.
    """
    return check_length(text, max_chars)
