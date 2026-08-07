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

# See rag_guardrails.py for why both import forms are needed.
try:
    from .checks import (
        DEFAULT_MAX_MESSAGE_CHARS,
        DEFAULT_PHONE_REGION,
        DEFAULT_PROMPT_INJECTION_CLASSIFIER_THRESHOLD,
        parse_public_contacts,
    )
    from .offensive_input_classifier import (
        DEFAULT_OFFENSIVE_INPUT_CLASSIFIER_MODEL,
        DEFAULT_OFFENSIVE_INPUT_CLASSIFIER_THRESHOLD,
        supported_offensive_input_classifier_models,
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
        parse_public_contacts,
    )
    from offensive_input_classifier import (
        DEFAULT_OFFENSIVE_INPUT_CLASSIFIER_MODEL,
        DEFAULT_OFFENSIVE_INPUT_CLASSIFIER_THRESHOLD,
        supported_offensive_input_classifier_models,
    )
    from prompt_injection_classifier import (
        DEFAULT_PROMPT_INJECTION_CLASSIFIER_MODEL,
        supported_prompt_injection_classifier_models,
    )

# How the admin panel is asked to render a field as a multi-line box.
#
# The nesting is the whole point, and getting it wrong fails silently. The panel
# reads `extra.type` from the published JSON Schema, so the marker has to sit in
# a nested `extra` object while `type` keeps its real value, `string`. Writing
# `json_schema_extra={"type": "TextArea"}` instead **replaces** `type`, which
# publishes a type that is not a valid JSON Schema type and puts the marker
# where the panel never looks: the field then renders as a single-line input and
# nothing anywhere reports a problem.
#
# `Field(extra={...})` produces exactly this schema too, and is what the other
# plugins on this instance use, but it is a deprecated Pydantic v2 spelling.
TEXT_AREA = {"extra": {"type": "TextArea"}}

DEFAULT_HELP_DESK_EMAIL = "helpdesk@example.org"

# What a phone number may be written with in the public-contacts list. Only a
# shape check: whether the digits form a real number is decided later, against
# the numbering plan of the stage doing the checking.
_PHONE_CHARACTERS = set("0123456789+-./() \u00A0")

# Bilingual in a single text, deliberately: the plugin does not detect the
# language of incoming messages, so it cannot pick one. A test asserts both
# languages are present.
DEFAULT_MESSAGE_TOO_LONG = (
    "La tua richiesta è troppo lunga per essere elaborata. "
    "Riformulala in modo più breve, indicando solo il servizio "
    "di tuo interesse. Per richieste complesse puoi scrivere "
    "all'Help Desk: {help_desk_email}\n\n"
    "Your request is too long to be processed. "
    "Please rephrase it more briefly, mentioning only the service "
    "you are asking about. For complex requests you can write to "
    "the Help Desk: {help_desk_email}"
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
    "all'Help Desk: {help_desk_email}\n\n"
    "To protect your data I cannot process messages containing personal "
    "information. Your message was not stored in the chatbot's memory. "
    "Please rephrase your request describing only the service or the problem, "
    "without e-mail addresses, phone numbers, tax codes or bank details. "
    "If your case requires personal data, write to the Help Desk: "
    "{help_desk_email}"
)

DEFAULT_OUTPUT_PERSONAL_DATA_DETECTED = (
    "Per tutelare i tuoi dati non posso inviare una risposta che contenga "
    "dati personali. Riformula la richiesta descrivendo solo il servizio o il "
    "problema, senza indirizzi e-mail, numeri di telefono, codice fiscale o "
    "dati bancari. Se il tuo caso richiede dati personali, scrivi "
    "all'Help Desk: {help_desk_email}\n\n"
    "To protect your data I cannot send a reply containing personal "
    "information. Please rephrase your request describing only the service or "
    "the problem, without e-mail addresses, phone numbers, tax codes or bank "
    "details. If your case requires personal data, write to the Help Desk: "
    "{help_desk_email}"
)

DEFAULT_PROMPT_INJECTION_DETECTED = (
    "Non posso elaborare richieste che cercano di modificare le istruzioni o "
    "di ottenere informazioni interne del chatbot. Riformula la domanda come "
    "richiesta di supporto sul servizio che ti interessa, senza chiedere "
    "di ignorare regole o rivelare prompt interni. Se hai bisogno di "
    "assistenza, scrivi all'Help Desk: {help_desk_email}\n\n"
    "I cannot process requests that try to alter the chatbot's instructions "
    "or obtain its internal information. Please rephrase your question as an "
    "help-desk request about the service you need, without asking to ignore "
    "rules or reveal hidden prompts. If you need assistance, write to the "
    "Help Desk: {help_desk_email}"
)


DEFAULT_OFFENSIVE_INPUT_DETECTED = (
    "Non posso elaborare messaggi con contenuti offensivi o violenti. "
    "Sono qui per aiutarti sui servizi del sito: riformula la richiesta descrivendo "
    "il problema tecnico che stai riscontrando e la seguo volentieri. "
    "Se preferisci parlare con una persona, scrivi all'Help Desk: "
    "{help_desk_email}\n\n"
    "I cannot process messages containing offensive or violent content. "
    "I am here to help you with site services: please rephrase your request "
    "describing the technical problem you are facing and I will gladly follow "
    "up. If you would rather talk to a person, write to the Help Desk: "
    "{help_desk_email}"
)


class PromptInjectionClassifierModel(str, Enum):
    LLAMA_PROMPT_GUARD_86M = "meta-llama/Llama-Prompt-Guard-2-86M"
    LLAMA_PROMPT_GUARD_22M = "meta-llama/Llama-Prompt-Guard-2-22M"
    DEBERTA_INJECTION = "deepset/deberta-v3-base-injection"


class OffensiveInputClassifierModel(str, Enum):
    IMSYPP_MULTILINGUAL = "IMSyPP/hate_speech_multilingual"
    HS_MULTILINGUAL_DNR = "patriciacarla/HS-multilingual-DNR"
    TEXTDETOX_TOXICITY = "textdetox/bert-multilingual-toxicity-classifier"


class RagGuardrailsSettings(BaseModel):
    help_desk_email: str = Field(
        default=DEFAULT_HELP_DESK_EMAIL,
        title="Help Desk e-mail",
        # description=(
            # "Address offered to the user when a request cannot be answered. "
            # "Write {help_desk_email} in any reply below to have it inserted here."
        # ),
    )

    public_service_contacts: str = Field(
        default="",
        title="Privacy guards: public service contacts (not treated as personal data)",
        # description=(
            # "Published service contacts, one per line, exempt from the privacy "
            # "guards on both stages. List only genuinely public ones."
        # ),
        json_schema_extra=TEXT_AREA,
    )

    max_message_chars: int = Field(
        default=DEFAULT_MAX_MESSAGE_CHARS,
        ge=0,
        title="Limits guard: maximum message length (characters)",
        # description=(
            # "Longer messages get a static reply without reaching the model. 0 "
            # "disables the check. Keep it below Rate Limiter's max_prompt_length."
        # ),
    )

    message_too_long: str = Field(
        default=DEFAULT_MESSAGE_TOO_LONG,
        title="Limits guard: reply — message too long",
        # description=(
            # "Sent when a message exceeds the maximum length. "
            # "Use {help_desk_email} as a placeholder for the address above."
        # ),
        json_schema_extra=TEXT_AREA,
    )

    detect_input_email: bool = Field(
        default=True,
        title="Input privacy guard: block e-mail addresses",
        # description=(
            # "Refuses messages containing an e-mail address. The Help Desk "
            # "address and the public contacts above are exempt."
        # ),
    )

    detect_input_codice_fiscale: bool = Field(
        default=True,
        title="Input privacy guard: block codice fiscale",
        # description=(
            # "Refuses messages containing a codice fiscale. The check character "
            # "is verified, so a lookalike string does not trigger a refusal."
        # ),
    )

    detect_input_iban: bool = Field(
        default=True,
        title="Input privacy guard: block IBAN",
        # description=(
            # "Refuses messages containing an IBAN. The mod-97 check digits are "
            # "verified, so an invalid IBAN does not trigger a refusal."
        # ),
    )

    detect_input_phone: bool = Field(
        default=True,
        title="Input privacy guard: block phone numbers",
        # description=(
            # "Refuses messages containing a phone number, validated against the "
            # "numbering plan below. All four detectors off disables the check."
        # ),
    )

    input_phone_region: str = Field(
        default=DEFAULT_PHONE_REGION,
        title="Input privacy guard: region for phone numbers written without a prefix",
        # description=(
            # "Two-letter country code, for example IT. Numbers written with an "
            # "international prefix are recognised whatever this value is."
        # ),
    )

    personal_data_detected: str = Field(
        default=DEFAULT_PERSONAL_DATA_DETECTED,
        title="Privacy guard: reply — personal data detected",
        # description=(
            # "Sent when a message is refused for containing personal data. "
            # "Use {help_desk_email} as a placeholder for the address above."
        # ),
        json_schema_extra=TEXT_AREA,
    )

    detect_output_email: bool = Field(
        default=True,
        title="Output privacy guard: block e-mail addresses",
        # description=(
            # "Refuses to send a generated reply containing an e-mail address. "
            # "The Help Desk address and the public contacts above are exempt."
        # ),
    )

    detect_output_codice_fiscale: bool = Field(
        default=True,
        title="Output privacy guard: block codice fiscale",
        # description=(
            # "Refuses to send a generated reply containing a codice fiscale. "
            # "The check character is verified."
        # ),
    )

    detect_output_iban: bool = Field(
        default=True,
        title="Output privacy guard: block IBAN",
        # description=(
            # "Refuses to send a generated reply containing an IBAN. The mod-97 "
            # "check digits are verified, so an invalid IBAN does not trigger a "
            # "refusal."
        # ),
    )

    detect_output_phone: bool = Field(
        default=True,
        title="Output privacy guard: block phone numbers",
        # description=(
            # "Refuses to send a generated reply containing a phone number, "
            # "validated against the numbering plan below."
        # ),
    )

    output_phone_region: str = Field(
        default=DEFAULT_PHONE_REGION,
        title="Output privacy guard: region for phone numbers written without a prefix",
        # description=(
            # "Two-letter country code, for example IT, for phone numbers in "
            # "generated replies written without an international prefix."
        # ),
    )

    output_personal_data_detected: str = Field(
        default=DEFAULT_OUTPUT_PERSONAL_DATA_DETECTED,
        title="Output privacy guard: reply — outgoing personal data detected",
        # description=(
            # "Sent when a generated reply is replaced because it contains "
            # "personal data. Use {help_desk_email} as a placeholder for the "
            # "address above."
        # ),
        json_schema_extra=TEXT_AREA,
    )

    detect_prompt_injection_custom: bool = Field(
        default=True,
        title="Security guard: block explicit prompt injection patterns",
        # description=(
            # "Refuses messages that try to override instructions or reveal "
            # "hidden prompts, using a built-in bilingual pattern set."
        # ),
    )

    detect_prompt_injection_classifier: bool = Field(
        default=False,
        title="Security guard: block prompt injection with local classifier",
        # description=(
            # "Runs a local model after the pattern detector. Ships off: it needs "
            # "a model download. On failure the message continues, with a warning."
        # ),
    )

    prompt_injection_classifier_model: PromptInjectionClassifierModel = Field(
        default=PromptInjectionClassifierModel(DEFAULT_PROMPT_INJECTION_CLASSIFIER_MODEL),
        title="Security guard: prompt injection classifier model",
        # description=(
            # "Local model used by the prompt injection classifier. The default "
            # "is preferred for Italian and English support messages."
        # ),
    )

    prompt_injection_classifier_threshold: float = Field(
        default=DEFAULT_PROMPT_INJECTION_CLASSIFIER_THRESHOLD,
        ge=0.0,
        le=1.0,
        title="Security guard: prompt injection classifier threshold",
        # description=(
            # "Minimum classifier confidence needed to block a message. Higher "
            # "values are more conservative and usually reduce false positives."
        # ),
    )

    huggingface_token: str = Field(
        default="",
        title="Security guard: Hugging Face token",
        # description=(
            # "Optional token for gated models. Prefer the HF_TOKEN environment "
            # "variable: it wins over this field and stays out of settings.json."
        # ),
    )

    prompt_injection_detected: str = Field(
        default=DEFAULT_PROMPT_INJECTION_DETECTED,
        title="Security guard: reply — prompt injection detected",
        # description=(
            # "Sent when the prompt injection guard blocks a message. "
            # "Use {help_desk_email} as a placeholder for the address above."
        # ),
        json_schema_extra=TEXT_AREA,
    )

    detect_offensive_input_classifier: bool = Field(
        default=False,
        title="Tone guard: block offensive incoming messages with local classifier",
        # description=(
            # "Refuses offensive or violent messages with a local model. Ships "
            # "off: it loads a second model and its precision is not yet measured."
        # ),
    )

    offensive_input_classifier_model: OffensiveInputClassifierModel = Field(
        default=OffensiveInputClassifierModel(DEFAULT_OFFENSIVE_INPUT_CLASSIFIER_MODEL),
        title="Tone guard: offensive input classifier model",
        # description=(
            # "Local model used by the offensive-input check. The default is "
            # "multilingual and covers Italian and English."
        # ),
    )

    offensive_input_classifier_threshold: float = Field(
        default=DEFAULT_OFFENSIVE_INPUT_CLASSIFIER_THRESHOLD,
        ge=0.0,
        le=1.0,
        title="Tone guard: offensive input classifier threshold",
        # description=(
            # "Minimum confidence needed to refuse. Careful: compared against the "
            # "SUM of the offensive classes, so stricter than it looks."
        # ),
    )

    offensive_input_detected: str = Field(
        default=DEFAULT_OFFENSIVE_INPUT_DETECTED,
        title="Tone guard: reply — offensive content detected",
        # description=(
            # "Sent when the offensive-input check refuses a message. "
            # "Use {help_desk_email} as a placeholder for the address above."
        # ),
        json_schema_extra=TEXT_AREA,
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

    @field_validator("public_service_contacts")
    @classmethod
    def _must_be_contacts(cls, value: str) -> str:
        # Rejected here rather than ignored at match time, because the silent
        # failure is the bad one: the entry never matches, answers keep being
        # replaced, and the administrator is looking at a list that appears to
        # say otherwise. The shape is all that is checked — whether a number is
        # valid depends on the region of the stage, which this validator cannot
        # know, so `_allowed_phone_numbers` drops what does not parse there.
        for entry in parse_public_contacts(value):
            if "@" in entry:
                if "@" not in entry.strip("@"):
                    raise ValueError(
                        f"{entry!r} is not an e-mail address, "
                        "for example helpdesk@example.org"
                    )
                continue
            if sum(character.isdigit() for character in entry) < 5:
                raise ValueError(
                    f"{entry!r} is neither an e-mail address nor a phone "
                    "number; write one contact per line"
                )
            if not all(character in _PHONE_CHARACTERS for character in entry):
                raise ValueError(
                    f"{entry!r} is not a phone number, "
                    "for example +390505091111"
                )
        return value.strip()

    @field_validator("input_phone_region", "output_phone_region")
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

    @field_validator("offensive_input_classifier_model", mode="before")
    @classmethod
    def _must_be_a_supported_offensive_model(
        cls, value: str | OffensiveInputClassifierModel
    ) -> str | OffensiveInputClassifierModel:
        raw_value = (
            value.value if isinstance(value, OffensiveInputClassifierModel) else value
        )
        if raw_value not in supported_offensive_input_classifier_models():
            allowed = ", ".join(supported_offensive_input_classifier_models())
            raise ValueError(f"unsupported model; choose one of: {allowed}")
        return value

    @field_validator(
        "message_too_long",
        "personal_data_detected",
        "output_personal_data_detected",
        "prompt_injection_detected",
        "offensive_input_detected",
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
    return RagGuardrailsSettings

