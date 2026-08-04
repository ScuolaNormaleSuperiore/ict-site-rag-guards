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
    from .checks import DEFAULT_MAX_MESSAGE_CHARS, DEFAULT_PHONE_REGION
except ImportError:  # pragma: no cover - depends on how the module is loaded
    from checks import DEFAULT_MAX_MESSAGE_CHARS, DEFAULT_PHONE_REGION

DEFAULT_HELP_DESK_EMAIL = "helpdesk@example.org"

# Bilingual in a single text, deliberately: the plugin does not detect the
# language of incoming messages, so it cannot pick one. A test asserts both
# languages are present. See DEV/TODO/RagGuardsPlan.md, Fase 2.
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

# The claim about storage is deliberately narrow, and true only on this path:
# an input guard answers from `fast_reply`, before the message reaches the
# vector database. Do not reuse this text after the recall, where the message
# is already in episodic memory. It also says "the chatbot's memory" rather
# than "not recorded", because the core logs every incoming message before any
# plugin runs; see DEV/AGENTS/PROJECT.md.
DEFAULT_PERSONAL_DATA_DETECTED = (
    "Per tutelare i tuoi dati non posso elaborare messaggi che contengono "
    "dati personali. Il messaggio non è stato memorizzato nella memoria del "
    "chatbot. Riformula la richiesta descrivendo solo il servizio o il "
    "problema, senza indirizzi e-mail, numeri di telefono, codice fiscale o "
    "dati bancari. Se il tuo caso richiede dati personali, scrivi "
    "all'Help Desk ICT: {help_desk_email}\n\n"
    "To protect your data I cannot process messages containing personal "
    "information. Your message was not stored in the chatbot's memory. "
    "Please rephrase your request describing only the service or the problem, "
    "without e-mail addresses, phone numbers, tax codes or bank details. "
    "If your case requires personal data, write to the ICT Help Desk: "
    "{help_desk_email}"
)


class IctSiteRagGuardsSettings(BaseModel):
    help_desk_email: str = Field(
        default=DEFAULT_HELP_DESK_EMAIL,
        title="Help Desk e-mail",
        description=(
            "Address offered to the user when a request cannot be answered. "
            "Write {help_desk_email} in any reply below to have it inserted here."
        ),
    )

    max_message_chars: int = Field(
        default=DEFAULT_MAX_MESSAGE_CHARS,
        ge=0,
        title="Max length guard: Maximum message length (characters)",
        description=(
            "Messages longer than this are answered with a static reply, without "
            "reaching the language model, so they cost no generation tokens. "
            "Set it to 0 to disable this check entirely. "
            "If the Rate Limiter plugin is also installed, keep this limit below "
            "its own max_prompt_length: for a message longer than that one but "
            "shorter than this, Rate Limiter is the plugin that stops it, with "
            "its own text, and it also records an infraction and suspends the "
            "user for several minutes."
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

    detect_email: bool = Field(
        default=True,
        title="Privacy guard: block e-mail addresses",
        description=(
            "Refuses messages containing an e-mail address. The Help Desk "
            "address configured above is not treated as personal data, so a "
            "user can mention it freely."
        ),
    )

    detect_codice_fiscale: bool = Field(
        default=True,
        title="Privacy guard: block codice fiscale",
        description=(
            "Refuses messages containing a codice fiscale. The check character "
            "is verified, so a sixteen-character string that merely looks like "
            "one does not trigger a refusal."
        ),
    )

    detect_iban: bool = Field(
        default=True,
        title="Privacy guard: block IBAN",
        description=(
            "Refuses messages containing an IBAN. The mod-97 check digits are "
            "verified, so an invalid IBAN does not trigger a refusal."
        ),
    )

    detect_phone: bool = Field(
        default=True,
        title="Privacy guard: block phone numbers",
        description=(
            "Refuses messages containing a phone number, landline or mobile, "
            "validated against the numbering plan of the region below rather "
            "than matched by shape — so dates and numeric error codes are not "
            "mistaken for numbers. Switching all four of these off disables the "
            "personal-data check entirely."
        ),
    )

    phone_region: str = Field(
        default=DEFAULT_PHONE_REGION,
        title="Region for phone numbers written without a prefix",
        description=(
            "Two-letter country code, for example IT. A number is only valid "
            "relative to a numbering plan: the same digits are a landline in "
            "one country and nothing in another. Numbers written with an "
            "international prefix are recognised whatever this value is."
        ),
    )

    personal_data_detected: str = Field(
        default=DEFAULT_PERSONAL_DATA_DETECTED,
        title="Reply: personal data detected",
        description=(
            "Sent when a message is refused for containing personal data. "
            "Use {help_desk_email} as a placeholder for the address above. "
            "It states that the message was not stored in the chatbot's "
            "memory, which is true on this path: nothing is retrieved, nothing "
            "is generated, and nothing reaches the vector database."
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
            raise ValueError(
                "must be an e-mail address, for example helpdesk@example.org"
            )
        return value

    @field_validator("phone_region")
    @classmethod
    def _must_be_a_region_code(cls, value: str) -> str:
        # An unknown region silently finds no numbers at all, which would
        # disable the phone detector without saying so. Catch the typo here.
        value = value.strip().upper()
        if len(value) != 2 or not value.isalpha():
            raise ValueError("must be a two-letter country code, for example IT")
        return value

    @field_validator("message_too_long", "personal_data_detected")
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
