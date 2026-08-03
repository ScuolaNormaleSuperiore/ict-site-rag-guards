"""Sanity checks for plugin metadata and shipped defaults."""

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def read_json(name: str):
    with (REPO_ROOT / name).open(encoding="utf-8") as handle:
        return json.load(handle)


class TestPluginMetadata:
    def test_plugin_json_has_the_minimum_expected_fields(self):
        plugin = read_json("plugin.json")

        required = {
            "name",
            "version",
            "description",
            "author_name",
            "author_url",
            "plugin_url",
            "tags",
            "thumb",
        }

        assert required <= set(plugin)

    def test_plugin_json_matches_the_repository_identity(self):
        plugin = read_json("plugin.json")

        assert plugin["name"] == "ICT Site RAG Guards"
        assert "guardrails" in plugin["description"].lower()
        assert "rag evidence gating" in plugin["description"].lower()


class TestShippedSettings:
    def test_settings_json_contains_the_first_guard_defaults(self):
        settings = read_json("settings.json")

        assert settings["help_desk_email"] == "helpdesk@sns.it"
        assert settings["max_message_chars"] == 1000
        assert "{help_desk_email}" in settings["message_too_long"]

    def test_settings_model_default_help_desk_matches_settings_json(self):
        settings = read_json("settings.json")
        settings_source = (REPO_ROOT / "settings.py").read_text(encoding="utf-8")
        match = re.search(
            r'^DEFAULT_HELP_DESK_EMAIL\s*=\s*"([^"]+)"',
            settings_source,
            re.MULTILINE,
        )

        assert match is not None
        assert match.group(1) == settings["help_desk_email"]
