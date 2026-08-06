"""Tests for the machinery shared by the two local classifiers.

These exercise the cache, the negative cache and the fail-open contract without
importing `transformers`: the module is always monkeypatched into `sys.modules`,
so the suite stays fast and local.

What is verified here used to live in `test_prompt_injection_classifier.py`. It
moved when the machinery did, because it never was about prompt injection: it is
about a model being loaded once, a failure being remembered, and one guard's
broken model not taking the other's down with it.
"""

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import classifier_runtime as runtime  # noqa: E402


A_MODEL = "meta-llama/Llama-Prompt-Guard-2-86M"
ANOTHER_MODEL = "deepset/deberta-v3-base-injection"


@pytest.fixture(autouse=True)
def reset_classifier_caches():
    """Isolate the two module-level caches, before *and* after each test.

    Clearing only on setup is not enough: the whole suite runs in one process, so
    the last test of this file would leave a failed model behind and the hook
    tests would then see a shipped default as unavailable. That is a failure this
    fixture was written to fix, not a hypothetical one.
    """
    runtime._CLASSIFIER_PIPELINES.clear()
    runtime._FAILED_CLASSIFIER_MODELS.clear()
    yield
    runtime._CLASSIFIER_PIPELINES.clear()
    runtime._FAILED_CLASSIFIER_MODELS.clear()


def fake_transformers(monkeypatch, pipeline_factory):
    """Install a stand-in `transformers` module exposing `pipeline`."""
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        type("M", (), {"pipeline": staticmethod(pipeline_factory)})(),
    )


class TestFailedLoadIsNotRetried:
    """The negative cache, and it is about cost rather than tidiness.

    Without it every message retries the load, and `transformers` re-resolves the
    repository on the Hub each time — so a gated model with no token costs a
    network round trip inside `fast_reply` per turn.
    """

    def failing_transformers(self, attempts, monkeypatch):
        def explode(task, model, token=None, **kwargs):
            attempts.append(model)
            raise OSError(f"401 Client Error: gated repo {model}")

        fake_transformers(monkeypatch, explode)

    def test_the_load_is_attempted_only_once(self, monkeypatch):
        attempts = []
        self.failing_transformers(attempts, monkeypatch)

        for _ in range(5):
            with pytest.raises(Exception):
                runtime.get_pipeline(A_MODEL)

        assert attempts == [A_MODEL]

    def test_later_calls_raise_without_touching_transformers(self, monkeypatch):
        attempts = []
        self.failing_transformers(attempts, monkeypatch)

        with pytest.raises(Exception):
            runtime.get_pipeline(A_MODEL)

        # Removing the module entirely: a retry would now raise ImportError, so
        # this asserts the second call never reaches the import at all.
        monkeypatch.delitem(sys.modules, "transformers")

        with pytest.raises(runtime.ClassifierUnavailable):
            runtime.get_pipeline(A_MODEL)

    def test_the_reason_is_kept_and_readable(self, monkeypatch):
        self.failing_transformers([], monkeypatch)

        with pytest.raises(Exception):
            runtime.get_pipeline(A_MODEL)

        reason = runtime.classifier_load_error(A_MODEL)
        assert reason is not None
        assert "gated repo" in reason

    def test_a_model_that_never_failed_reports_no_error(self):
        assert runtime.classifier_load_error(ANOTHER_MODEL) is None

    def test_one_model_failing_does_not_block_another(self, monkeypatch):
        def selectively_explode(task, model, token=None, **kwargs):
            if model.startswith("meta-llama/"):
                raise OSError("401 Client Error: gated repo")
            return lambda text, **call_kwargs: [{"label": "INJECTION", "score": 0.95}]

        fake_transformers(monkeypatch, selectively_explode)

        with pytest.raises(Exception):
            runtime.get_pipeline(A_MODEL)

        # The cache is per model, and the two guards share it: a broken model of
        # one must not make the other's model unavailable, and switching to a
        # working model in the admin panel must not need a restart.
        assert runtime.get_pipeline(ANOTHER_MODEL)
        assert runtime.classifier_load_error(ANOTHER_MODEL) is None


class TestPipelineCache:
    def test_pipeline_is_cached_per_model(self, monkeypatch):
        calls = []

        def fake_pipeline(task, model, token=None, **kwargs):
            calls.append((task, model))
            return lambda text, **call_kwargs: [{"label": "MALICIOUS", "score": 0.91}]

        fake_transformers(monkeypatch, fake_pipeline)

        first = runtime.get_pipeline(A_MODEL)
        second = runtime.get_pipeline(A_MODEL)

        assert first is second
        assert calls == [("text-classification", A_MODEL)]

    def test_load_arguments_reach_transformers(self, monkeypatch):
        captured = {}

        def fake_pipeline(task, model, token=None, **kwargs):
            captured["token"] = token
            captured["kwargs"] = kwargs
            return lambda text, **call_kwargs: []

        fake_transformers(monkeypatch, fake_pipeline)

        runtime.get_pipeline(A_MODEL, token="hf_test", device=-1)

        assert captured["token"] == "hf_test"
        assert captured["kwargs"] == {"device": -1}


class TestModelLabels:
    """Reading the labels a model can return, which is how a mapping is checked."""

    def pipeline_with(self, id2label):
        config = type("Config", (), {"id2label": id2label})
        model = type("Model", (), {"config": config})
        return type("Pipeline", (), {"model": model})()

    def test_labels_are_returned_in_index_order(self):
        pipeline = self.pipeline_with({1: "LABEL_1", 0: "LABEL_0", 2: "LABEL_2"})

        assert runtime.model_labels(pipeline) == ("LABEL_0", "LABEL_1", "LABEL_2")

    def test_a_pipeline_without_a_config_yields_nothing(self):
        # Degrading into "not verified" rather than into a failure: a caller that
        # cannot read the labels must not take the turn down over it.
        assert runtime.model_labels(object()) == ()
