"""Plugin settings, exposed in the Cheshire Cat admin panel.

This model is what the admin form is built from, and its defaults are what
`settings.json` gets created with the first time the plugin is activated.

Decision defaults are not redefined here: `max_message_chars` takes its default
from `checks.py`, which stays the single source of truth for the logic and keeps
being testable without Cheshire Cat.
"""

from cat.mad_hatter.decorators import plugin
from pydantic import BaseModel, Field, field_validator

# See ict_site_rag_guards.py for why both import forms are needed.
try:
    from .checks import DEFAULT_MAX_MESSAGE_CHARS
except ImportError:  # pragma: no cover - depends on how the module is loaded
    from checks import DEFAULT_MAX_MESSAGE_CHARS

DEFAULT_HELP_DESK_EMAIL = "helpdesk@sns.it"

# Bilingual in a single text until language detection (Fase 2) populates
# `cat.working_memory.user_language` and lets us pick one language per turn.
DEFAULT_MESSAGE_TOO_LONG = (
    "La tua richiesta è troppo lunga per essere elaborata. "
    "Riformulala in modo più breve, indicando solo il servizio ICT "
    "di tuo interesse. Per richieste complesse puoi scrivere "
    "all'Help Desk ICT: {help_desk_email}\n\n"
    "Your request is too long to be processed. "
    "Please rephrase it more briefly, mentioning only the ICT service "
    "you are asking about. For complex requests you can write to "
    "the ICT Help Desk: {help_desk_email}"
)


class IctSiteRagGuardsSettings(BaseModel):
    help_desk_email: str = Field(
        default=DEFAULT_HELP_DESK_EMAIL,
        title="Help Desk email",
        description=(
            "Address offered to the user when a request cannot be answered. "
            "Write {help_desk_email} in any reply below to have it inserted here."
        ),
    )

    max_message_chars: int = Field(
        default=DEFAULT_MAX_MESSAGE_CHARS,
        ge=0,
        title="Maximum message length (characters)",
        description=(
            "Messages longer than this are answered with a static reply, without "
            "reaching the language model, so they cost no generation tokens. "
            "0 disables the check. Keep this below the Rate Limiter plugin's own "
            "limit, otherwise that plugin answers first with its own message."
        ),
    )

    message_too_long: str = Field(
        default=DEFAULT_MESSAGE_TOO_LONG,
        title="Reply: message too long",
        description=(
            "Sent when a message exceeds the maximum length. "
            "Use {help_desk_email} as a placeholder for the address above."
        ),
        extra={"type": "TextArea"},
    )

    @field_validator("help_desk_email")
    @classmethod
    def _must_look_like_an_address(cls, value: str) -> str:
        # Deliberately minimal: pydantic's EmailStr needs the email-validator
        # package, which is not installed in the core image, and a wrong address
        # here is a content mistake, not a security boundary.
        value = value.strip()
        if "@" not in value.strip("@"):
            raise ValueError("must be an email address, for example helpdesk@sns.it")
        return value

    @field_validator("message_too_long")
    @classmethod
    def _reply_must_not_be_empty(cls, value: str) -> str:
        # An empty reply would send the user a blank message, which is worse
        # than letting the model answer.
        value = value.strip()
        if not value:
            raise ValueError("the reply text cannot be empty")
        return value


@plugin
def settings_model():
    """Return the Pydantic model the admin panel builds its form from."""
    return IctSiteRagGuardsSettings
