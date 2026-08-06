"""Local classifier for prompt-injection attempts.

Only the decision rule lives here: one expected label per model, compared against
a threshold. The machinery around it — pipeline cache, negative cache on failed
loads, lazy `transformers` import, fail-open contract — is in
`classifier_runtime.py`, shared with the offensive-input classifier.

The plugin must keep working when the dependency is missing or the model cannot
load: this classifier is fail-open by design in v1.
"""

from __future__ import annotations

try:
    from .classifier_runtime import (
        ClassifierUnavailable,
        classifier_load_error,
        get_pipeline,
    )
except ImportError:  # pragma: no cover - depends on how the module is loaded
    from classifier_runtime import (
        ClassifierUnavailable,
        classifier_load_error,
        get_pipeline,
    )

# Re-exported so callers that already import them from here keep working, and so
# this module reads as the whole prompt-injection story in one place.
__all__ = [
    "ClassifierUnavailable",
    "DEFAULT_PROMPT_INJECTION_CLASSIFIER_MODEL",
    "PROMPT_INJECTION_CLASSIFIER_LABELS",
    "classifier_load_error",
    "classify_prompt_injection",
    "supported_prompt_injection_classifier_models",
]


DEFAULT_PROMPT_INJECTION_CLASSIFIER_MODEL = "meta-llama/Llama-Prompt-Guard-2-86M"

PROMPT_INJECTION_CLASSIFIER_LABELS = {
    "meta-llama/Llama-Prompt-Guard-2-86M": "MALICIOUS",
    "meta-llama/Llama-Prompt-Guard-2-22M": "MALICIOUS",
    "deepset/deberta-v3-base-injection": "INJECTION",
}


def supported_prompt_injection_classifier_models() -> tuple[str, ...]:
    return tuple(PROMPT_INJECTION_CLASSIFIER_LABELS)


def classify_prompt_injection(
    text: str,
    model_name: str = DEFAULT_PROMPT_INJECTION_CLASSIFIER_MODEL,
    threshold: float = 0.85,
    max_length: int | None = None,
    token: str | None = None,
) -> dict[str, str | float | bool | None]:
    """Classify a message and decide whether it must be blocked.

    Returns a small dict so callers can log what happened without relying on the
    raw pipeline response shape.
    """
    if not text.strip():
        return {"triggered": False, "label": None, "score": 0.0}

    expected_label = PROMPT_INJECTION_CLASSIFIER_LABELS[model_name]
    pipeline_kwargs = {}
    if max_length is not None and max_length > 0:
        pipeline_kwargs["truncation"] = True
        pipeline_kwargs["max_length"] = max_length

    result = get_pipeline(model_name, token=token)(text, **pipeline_kwargs)
    top = result[0] if isinstance(result, list) else result

    label = str(top.get("label", "")).strip().upper()
    score = float(top.get("score", 0.0) or 0.0)
    return {
        "triggered": label == expected_label and score >= threshold,
        "label": label,
        "score": score,
    }
