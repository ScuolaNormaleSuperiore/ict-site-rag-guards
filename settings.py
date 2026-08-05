"""Plugin settings, exposed in the Cheshire Cat admin panel.

This model is what the admin form is built from, and its defaults are what
`settings.json` gets created with the first time the plugin is activated.

Decision defaults are not redefined here: `max_message_chars` takes its default
from `checks.py`, which stays the single source of truth for the logic and keeps
being testable without Cheshire Cat.
"""

from enum import Enum

from cat.mad_hatter.decorators import plugin
from pydantic import BaseModel, Field, field_validator

# See ict_site_rag_guards.py for why both import forms are needed.
try:
    from .checks import (
        DEFAULT_MAX_MESSAGE_CHARS,
        DEFAULT_PHONE_REGION,
        DEFAULT_PROMPT_INJECTION_CLASSIFIER_THRESHOLD,
    )
    from .prompt_injection_classifier import (
        DEFAULT_PROMPT_INJECTION_CLASSIFIER_MODEL,
        supported_prompt_injection_classifier_models,
    )
except ImportError:  # pragma: no cover - depends on how the module is loaded
    from checks import (
        DEFAULT_MAX_MESSAGE_CHARS,
        DEFAULT_PHONE_REGION,
        DEFAULT_PROMPT_INJECTION_CLASSIFIER_THRESHOLD,
    )
    from prompt_injection_classifier import (
        DEFAULT_PROMPT_INJECTION_CLASSIFIER_MODEL,
        supported_prompt_injection_classifier_models,
    )

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

DEFAULT_PROMPT_INJECTION_DETECTED = (
    "Non posso elaborare richieste che cercano di modificare le istruzioni o "
    "di ottenere informazioni interne del chatbot. Riformula la domanda come "
    "richiesta di supporto ICT sul servizio che ti interessa, senza chiedere "
    "di ignorare regole o rivelare prompt interni. Se hai bisogno di "
    "assistenza, scrivi all'Help Desk ICT: {help_desk_email}\n\n"
    "I cannot process requests that try to alter the chatbot's instructions "
    "or obtain its internal information. Please rephrase your question as an "
    "ICT support request about the service you need, without asking to ignore "
    "rules or reveal hidden prompts. If you need assistance, write to the ICT "
    "Help Desk: {help_desk_email}"
)


class PromptInjectionClassifierModel(str, Enum):
    LLAMA_PROMPT_GUARD_86M = "meta-llama/Llama-Prompt-Guard-2-86M"
    LLAMA_PROMPT_GUARD_22M = "meta-llama/Llama-Prompt-Guard-2-22M"
    DEBERTA_INJECTION = "deepset/deberta-v3-base-injection"


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

    detect_prompt_injection_custom: bool = Field(
        default=True,
        title="Security guard: block explicit prompt injection patterns",
        description=(
            "Refuses messages that explicitly try to override instructions, "
            "bypass rules, or reveal hidden prompts, using a conservative "
            "built-in bilingual pattern set."
        ),
    )

    detect_prompt_injection_classifier: bool = Field(
        default=True,
        title="Security guard: block prompt injection with local classifier",
        description=(
            "Runs a local text-classification model after the custom detector. "
            "If loading or inference fails, the message continues and the "
            "plugin logs a warning."
        ),
    )

    prompt_injection_classifier_model: PromptInjectionClassifierModel = Field(
        default=PromptInjectionClassifierModel(DEFAULT_PROMPT_INJECTION_CLASSIFIER_MODEL),
        title="Security guard: prompt injection classifier model",
        description=(
            "Local model used by the prompt injection classifier. The default "
            "is preferred for Italian and English support messages."
        ),
    )

    prompt_injection_classifier_threshold: float = Field(
        default=DEFAULT_PROMPT_INJECTION_CLASSIFIER_THRESHOLD,
        ge=0.0,
        le=1.0,
        title="Security guard: prompt injection classifier threshold",
        description=(
            "Minimum classifier confidence needed to block a message. Higher "
            "values are more conservative and usually reduce false positives."
        ),
    )

    huggingface_token: str = Field(
        default="",
        title="Security guard: Hugging Face token",
        description=(
            "Optional user access token for gated Hugging Face models. Needed "
            "only for classifier models that require authenticated access, "
            "such as the Meta Llama Prompt Guard models. If the HF_TOKEN "
            "environment variable is set, it takes precedence over this field."
        ),
    )

    prompt_injection_detected: str = Field(
        default=DEFAULT_PROMPT_INJECTION_DETECTED,
        title="Reply: prompt injection detected",
        description=(
            "Sent when the prompt injection guard blocks a message, whether it "
            "was detected by the custom patterns or by the local classifier. "
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

    @field_validator("prompt_injection_classifier_model", mode="before")
    @classmethod
    def _must_be_a_supported_classifier_model(
        cls, value: str | PromptInjectionClassifierModel
    ) -> str | PromptInjectionClassifierModel:
        raw_value = value.value if isinstance(value, PromptInjectionClassifierModel) else value
        if raw_value not in supported_prompt_injection_classifier_models():
            allowed = ", ".join(supported_prompt_injection_classifier_models())
            raise ValueError(f"unsupported model; choose one of: {allowed}")
        return value

    @field_validator(
        "message_too_long",
        "personal_data_detected",
        "prompt_injection_detected",
    )
    @classmethod
    def _reply_must_not_be_empty(cls, value: str) -> str:
        # An empty reply would send the user a blank message, which is worse
        # than letting the model answer.
        value = value.strip()
        if not value:
            raise ValueError("the reply text cannot be empty")
        return value

    @field_validator("huggingface_token")
    @classmethod
    def _strip_huggingface_token(cls, value: str) -> str:
        return value.strip()


@plugin
def settings_model():
    """Return the Pydantic model the admin panel builds its form from."""
    return IctSiteRagGuardsSettings
