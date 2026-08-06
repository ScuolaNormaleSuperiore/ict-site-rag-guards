"""Shared runtime for the local text-classification models.

Two guards run a local model — the prompt-injection classifier and the
offensive-input classifier — and they need exactly the same machinery around it:
a lazy import of `transformers`, one pipeline per model kept in memory, a memory
of the loads that already failed, and a fail-open contract. That machinery lives
here so it exists once.

The caches are keyed by model name and shared by every caller, which is the
correct behaviour rather than a side effect: a model is loaded once per process,
whoever asks for it. It also keeps `classifier_load_error()` a single function,
so a caller that needs to know whether a model is usable asks one question
regardless of which guard it belongs to.

This module imports nothing from `cat` beyond the logger, and `transformers` only
inside `get_pipeline()`. Nothing here decides whether a message is blocked: that
belongs to the classifier modules, because the decision rule differs between
them — one label against a threshold for prompt injection, a sum of labels for
offensive input.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from cat.log import log as runtime_log
except Exception:  # pragma: no cover - available only with the core importable
    runtime_log = logging.getLogger(__name__)


_CLASSIFIER_PIPELINES: dict[str, Any] = {}

# Models whose load already failed, with the reason. This is a negative cache and
# it exists for cost, not for tidiness: without it every message retries the
# load, and `transformers` re-resolves the repository on the Hub each time, so a
# gated model with no token costs a network round trip inside `fast_reply`, the
# hook that runs before everything else.
#
# Retrying cannot help anyway: the token comes from the settings or from the
# environment, and neither changes without the plugin reloading, which clears
# this dict along with the successful pipelines above.
_FAILED_CLASSIFIER_MODELS: dict[str, str] = {}


class ClassifierUnavailable(RuntimeError):
    """A model that already failed to load and is not being retried."""


def classifier_load_error(model_name: str) -> str | None:
    """Why this model is unavailable, or None if it has not failed.

    Lets callers keep their own reporting honest — a check that cannot run must
    not be listed among the ones covering a turn.
    """
    return _FAILED_CLASSIFIER_MODELS.get(model_name)


def get_pipeline(model_name: str, token: str | None = None, **pipeline_kwargs):
    """Return the cached text-classification pipeline for `model_name`.

    Raises `ClassifierUnavailable` for a model whose load already failed, and
    whatever `transformers` raises the first time a load fails. Both are errors
    the callers turn into fail-open behaviour: a classifier that cannot run must
    leave the message alone, never take the turn down.

    `pipeline_kwargs` reaches `transformers.pipeline()` and is part of the cache
    identity only through the model name, which is deliberate: the two guards
    pass different arguments — `top_k=None` for the one that needs every score —
    and a model configured one way must not be silently reused with the other
    configuration. Callers therefore must not vary these arguments for the same
    model, and today none does: each model belongs to one guard.
    """
    pipeline = _CLASSIFIER_PIPELINES.get(model_name)
    if pipeline is not None:
        # INFO for v1, deliberately, even though this fires on every message
        # that reaches a classifier: while the feature is being evaluated,
        # seeing the pipeline being reused is worth the volume. It is the one
        # line this plugin writes per message at the default level — reconsider
        # demoting it to DEBUG once real traffic shows whether it is noise.
        # See DOC/SecurityGuards.md, section *Logging and measurement*.
        runtime_log.info(
            "[ict-site-rag-guards] classifier pipeline cache hit "
            f"for model {model_name}"
        )
        return pipeline

    previous_error = _FAILED_CLASSIFIER_MODELS.get(model_name)
    if previous_error is not None:
        # Nothing is logged here: the failure was reported when it happened, and
        # repeating it once per message is the flood this cache removes.
        raise ClassifierUnavailable(previous_error)

    from transformers import pipeline as transformers_pipeline

    runtime_log.info(
        "[ict-site-rag-guards] loading classifier model "
        f"{model_name} into memory; Transformers will use the local Hugging Face "
        "cache when available and download missing files if needed"
    )
    try:
        pipeline = transformers_pipeline(
            "text-classification",
            model=model_name,
            token=token,
            **pipeline_kwargs,
        )
    except Exception as error:
        _FAILED_CLASSIFIER_MODELS[model_name] = str(error)
        runtime_log.warning(
            "[ict-site-rag-guards] failed to load classifier "
            f"model {model_name}: {error}; it will not be retried until the "
            "plugin reloads"
        )
        raise

    runtime_log.info(
        "[ict-site-rag-guards] classifier model "
        f"{model_name} loaded and cached in memory"
    )
    _CLASSIFIER_PIPELINES[model_name] = pipeline
    return pipeline


def model_labels(pipeline) -> tuple[str, ...]:
    """The labels a loaded model can actually return, in index order.

    Read from the model configuration rather than assumed, because that is the
    only place the truth is: `pipeline()` returns whatever `id2label` says, and
    for these models it says `LABEL_0`, `LABEL_1`, not the readable class names
    the model cards describe.

    Returns an empty tuple when the configuration cannot be read, so a caller
    validating its label mapping degrades into *not verifying* rather than into
    a failure.
    """
    try:
        id2label = pipeline.model.config.id2label
    except AttributeError:  # pragma: no cover - defensive, all models carry it
        return ()
    return tuple(str(id2label[index]) for index in sorted(id2label))
