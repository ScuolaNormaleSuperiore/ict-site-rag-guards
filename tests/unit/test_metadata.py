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
        assert "rag flow" in plugin["description"].lower()
        assert "retrieval or generation" in plugin["description"].lower()


class TestShippedSettings:
    """The defaults the plugin is distributed with.

    Read from the source files, never from `settings.json`: that file holds the
    configuration of one installation, it is excluded from version control, and
    it does not exist at all until the plugin is activated for the first time.
    Asserting on it would make these tests fail on a fresh clone for a reason
    that has nothing to do with the plugin.

    The source is read as text rather than imported, so this module keeps
    needing nothing but the standard library, which is what allows it to live in
    tests/unit.
    """

    def settings_source(self) -> str:
        return (REPO_ROOT / "settings.py").read_text(encoding="utf-8")

    def test_the_default_help_desk_address_looks_like_an_email(self):
        match = re.search(
            r'^DEFAULT_HELP_DESK_EMAIL\s*=\s*"([^"]+)"',
            self.settings_source(),
            re.MULTILINE,
        )

        assert match is not None, "DEFAULT_HELP_DESK_EMAIL is not defined"
        address = match.group(1)
        assert "@" in address.strip("@"), f"not an email address: {address}"

    def test_the_default_reply_carries_the_email_placeholder(self):
        # Without the placeholder, changing the address in the admin panel would
        # leave the old one in the text shown to the user.
        match = re.search(
            r"^DEFAULT_MESSAGE_TOO_LONG\s*=\s*\((.*?)\)$",
            self.settings_source(),
            re.MULTILINE | re.DOTALL,
        )

        assert match is not None, "DEFAULT_MESSAGE_TOO_LONG is not defined"
        assert "{help_desk_email}" in match.group(1)

    def test_the_length_limit_has_a_single_source_of_truth(self):
        # The settings model must take its default from checks.py instead of
        # repeating a number, otherwise the two can drift apart.
        assert "DEFAULT_MAX_MESSAGE_CHARS" in self.settings_source()

        checks_source = (REPO_ROOT / "checks.py").read_text(encoding="utf-8")
        match = re.search(
            r"^DEFAULT_MAX_MESSAGE_CHARS\s*=\s*(\d+)",
            checks_source,
            re.MULTILINE,
        )

        assert match is not None, "DEFAULT_MAX_MESSAGE_CHARS is not defined"
        assert int(match.group(1)) > 0
