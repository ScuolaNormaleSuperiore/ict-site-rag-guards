"""Runtime support for the prompt-injection classifier.

This module deliberately imports `transformers` lazily. The plugin must keep
working when the dependency is missing or the model cannot load: the prompt
injection classifier is fail-open by design in v1.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from cat.log import log as runtime_log
except Exception:  # pragma: no cover - available only with the core importable
    runtime_log = logging.getLogger(__name__)


DEFAULT_PROMPT_INJECTION_CLASSIFIER_MODEL = "meta-llama/Llama-Prompt-Guard-2-86M"

PROMPT_INJECTION_CLASSIFIER_LABELS = {
    "meta-llama/Llama-Prompt-Guard-2-86M": "MALICIOUS",
    "meta-llama/Llama-Prompt-Guard-2-22M": "MALICIOUS",
    "deepset/deberta-v3-base-injection": "INJECTION",
}

_CLASSIFIER_PIPELINES: dict[str, Any] = {}


def supported_prompt_injection_classifier_models() -> tuple[str, ...]:
    return tuple(PROMPT_INJECTION_CLASSIFIER_LABELS)


def _get_pipeline(model_name: str, token: str | None = None):
    pipeline = _CLASSIFIER_PIPELINES.get(model_name)
    if pipeline is not None:
        runtime_log.info(
            "[ict-site-rag-guards] prompt-injection classifier pipeline cache hit "
            f"for model {model_name}"
        )
        return pipeline

    from transformers import pipeline as transformers_pipeline

    runtime_log.info(
        "[ict-site-rag-guards] loading prompt-injection classifier model "
        f"{model_name} into memory; Transformers will use the local Hugging Face "
        "cache when available and download missing files if needed"
    )
    try:
        pipeline = transformers_pipeline(
            "text-classification",
            model=model_name,
            token=token,
        )
    except Exception as error:
        runtime_log.warning(
            "[ict-site-rag-guards] failed to load prompt-injection classifier "
            f"model {model_name}: {error}"
        )
        raise

    runtime_log.info(
        "[ict-site-rag-guards] prompt-injection classifier model "
        f"{model_name} loaded and cached in memory"
    )
    _CLASSIFIER_PIPELINES[model_name] = pipeline
    return pipeline


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

    result = _get_pipeline(model_name, token=token)(text, **pipeline_kwargs)
    top = result[0] if isinstance(result, list) else result

    label = str(top.get("label", "")).strip().upper()
    score = float(top.get("score", 0.0) or 0.0)
    return {
        "triggered": label == expected_label and score >= threshold,
        "label": label,
        "score": score,
    }
