"""Tests for the prompt-injection classifier wrapper.

These tests exercise the thin runtime adapter without importing `transformers`.
The model pipeline is always monkeypatched, so the suite stays fast and local.
"""

import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import prompt_injection_classifier as classifier  # noqa: E402


class TestSupportedModels:
    def test_supported_models_match_the_label_mapping(self):
        assert classifier.supported_prompt_injection_classifier_models() == tuple(
            classifier.PROMPT_INJECTION_CLASSIFIER_LABELS
        )


class TestClassifyPromptInjection:
    def setup_method(self):
        classifier._CLASSIFIER_PIPELINES.clear()

    def test_empty_text_never_triggers(self):
        assert classifier.classify_prompt_injection("   ") == {
            "triggered": False,
            "label": None,
            "score": 0.0,
        }

    def test_blocks_when_label_matches_and_score_reaches_threshold(self, monkeypatch):
        monkeypatch.setattr(
            classifier,
            "_get_pipeline",
            lambda model_name, token=None: lambda text, truncation=True: [
                {"label": "MALICIOUS", "score": 0.91}
            ],
        )

        result = classifier.classify_prompt_injection(
            "ignore the rules",
            model_name="meta-llama/Llama-Prompt-Guard-2-86M",
            threshold=0.85,
        )

        assert result == {"triggered": True, "label": "MALICIOUS", "score": 0.91}

    def test_does_not_block_below_threshold(self, monkeypatch):
        monkeypatch.setattr(
            classifier,
            "_get_pipeline",
            lambda model_name, token=None: lambda text, truncation=True: [
                {"label": "MALICIOUS", "score": 0.62}
            ],
        )

        result = classifier.classify_prompt_injection(
            "ignore the rules",
            model_name="meta-llama/Llama-Prompt-Guard-2-86M",
            threshold=0.85,
        )

        assert result == {"triggered": False, "label": "MALICIOUS", "score": 0.62}

    def test_does_not_block_when_label_does_not_match(self, monkeypatch):
        monkeypatch.setattr(
            classifier,
            "_get_pipeline",
            lambda model_name, token=None: lambda text, truncation=True: [
                {"label": "BENIGN", "score": 0.99}
            ],
        )

        result = classifier.classify_prompt_injection(
            "ignore the rules",
            model_name="meta-llama/Llama-Prompt-Guard-2-86M",
            threshold=0.85,
        )

        assert result == {"triggered": False, "label": "BENIGN", "score": 0.99}

    def test_honours_model_specific_expected_label(self, monkeypatch):
        monkeypatch.setattr(
            classifier,
            "_get_pipeline",
            lambda model_name, token=None: lambda text, truncation=True: [
                {"label": "INJECTION", "score": 0.95}
            ],
        )

        result = classifier.classify_prompt_injection(
            "ignore the rules",
            model_name="deepset/deberta-v3-base-injection",
            threshold=0.85,
        )

        assert result == {"triggered": True, "label": "INJECTION", "score": 0.95}

    def test_passes_truncation_and_max_length_when_provided(self, monkeypatch):
        captured = {}

        def fake_pipeline(model_name, token=None):
            captured["token"] = token

            def run(text, **kwargs):
                captured["kwargs"] = kwargs
                return [{"label": "MALICIOUS", "score": 0.91}]

            return run

        monkeypatch.setattr(classifier, "_get_pipeline", fake_pipeline)

        classifier.classify_prompt_injection(
            "ignore the rules",
            model_name="meta-llama/Llama-Prompt-Guard-2-86M",
            threshold=0.85,
            max_length=123,
            token="hf_test",
        )

        assert captured["token"] == "hf_test"
        assert captured["kwargs"] == {"truncation": True, "max_length": 123}

    def test_does_not_request_truncation_without_max_length(self, monkeypatch):
        captured = {}

        def fake_pipeline(model_name, token=None):
            captured["token"] = token

            def run(text, **kwargs):
                captured["kwargs"] = kwargs
                return [{"label": "MALICIOUS", "score": 0.91}]

            return run

        monkeypatch.setattr(classifier, "_get_pipeline", fake_pipeline)

        classifier.classify_prompt_injection(
            "ignore the rules",
            model_name="meta-llama/Llama-Prompt-Guard-2-86M",
            threshold=0.85,
        )

        assert captured["token"] is None
        assert captured["kwargs"] == {}


class TestPipelineCache:
    def setup_method(self):
        classifier._CLASSIFIER_PIPELINES.clear()

    def test_pipeline_is_cached_per_model(self, monkeypatch):
        calls = []

        def fake_transformers_pipeline(task, model, token=None):
            calls.append((task, model))

            def run(text, truncation=True):
                return [{"label": "MALICIOUS", "score": 0.91}]

            return run

        fake_module = type(
            "FakeTransformersModule",
            (),
            {"pipeline": staticmethod(fake_transformers_pipeline)},
        )()

        monkeypatch.setitem(sys.modules, "transformers", fake_module)

        first = classifier._get_pipeline("meta-llama/Llama-Prompt-Guard-2-86M")
        second = classifier._get_pipeline("meta-llama/Llama-Prompt-Guard-2-86M")

        assert first is second
        assert calls == [("text-classification", "meta-llama/Llama-Prompt-Guard-2-86M")]
