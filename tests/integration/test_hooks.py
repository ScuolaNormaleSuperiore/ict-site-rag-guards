"""Tests for the two hooks and for the configuration.

These do not need a running Cat, an LLM or a vector database: a fake `cat`
object exposing a working memory, and optionally a plugin registry, is enough.
They do need the core to be importable, because the module under test imports
`cat.log` and `cat.mad_hatter.decorators`, so they are skipped where it is not:

    .\\run-tests.ps1        (or ./run-tests.sh)

Two things here are worth more than the sum of the assertions.

The hook priority: `fast_reply` hooks are piped in descending priority order and
the last non-None return wins, so this plugin must stay below the other plugins
to have its reply delivered. A priority raised above 1 by mistake would silently
hand over control to `Rate Limiter`, with no error anywhere.

The verdict carrier: a verdict written by one hook and never read by the other
produces no error at all. The chatbot keeps answering, simply without being
guarded any more.
"""

import sys
import types
from pathlib import Path

import pytest

# The Cat imports every .py in the plugin folder, this file included, under a
# package name where a bare `import checks` does not resolve. Without this the
# imports below raise during activation and the core logs a plugin load error.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import checks  # noqa: E402  (import after the path fix, on purpose)

# importorskip is still needed for the other environment: on a developer machine
# without the core dependencies these modules cannot be imported at all, and
# skipping is the wanted outcome there.
guards = pytest.importorskip(
    "ict_site_rag_guards",
    reason="needs the Cheshire Cat core importable; run inside the container",
)
settings_module = pytest.importorskip("settings")

# The @hook decorator replaces the function with a CatHook object, so the
# callable under test is reached through `.function`.
guard_input_message = guards.guard_input_message.function
dispatch_fast_reply = guards.dispatch_fast_reply.function

# The priority the Rate Limiter plugin gets from a bare @hook decorator.
OTHER_PLUGIN_DEFAULT_PRIORITY = 1


def make_cat(stored_settings=None):
    """A stand-in for StrayCat exposing only what the hooks actually use.

    With `stored_settings` omitted the fake has no plugin registry at all,
    which is also what exercises the fallback to the model defaults.
    """
    cat = types.SimpleNamespace(working_memory=types.SimpleNamespace())
    if stored_settings is not None:
        fake_plugin = types.SimpleNamespace(load_settings=lambda: stored_settings)
        cat.mad_hatter = types.SimpleNamespace(get_plugin=lambda: fake_plugin)
    return cat


def send(cat, text, incoming=None):
    """Simulate one turn reaching the `fast_reply` hook.

    The core stores the parsed message in working memory before running the
    hook, and passes along whatever the previous hooks returned.
    """
    cat.working_memory.user_message_json = {"text": text}
    return guard_input_message({} if incoming is None else incoming, cat)


def verdict_of(cat):
    return getattr(cat.working_memory, guards.VERDICT_ATTRIBUTE, "ATTRIBUTE MISSING")


class TestHookRegistration:
    def test_hooks_are_bound_to_the_core_hook_names(self):
        # The function names are ours; the names the core dispatches on are not.
        assert guards.guard_input_message.name == "fast_reply"
        assert guards.dispatch_fast_reply.name == "agent_fast_reply"

    def test_input_guard_runs_after_the_other_plugins(self):
        # The whole independence from Rate Limiter rests on this comparison:
        # hooks are piped in descending priority and the last reply wins.
        assert guards.guard_input_message.priority < OTHER_PLUGIN_DEFAULT_PRIORITY

    def test_dispatcher_overrides_the_core_plugin(self):
        # Core plugin hooks have priority 0; this one must be higher to take over.
        assert guards.dispatch_fast_reply.priority > 0


class TestInputGuard:
    def test_answers_immediately_when_the_message_is_too_long(self):
        cat = make_cat()

        result = send(cat, "a" * 5000)

        # The core returns straight away only on the "output" key.
        assert "output" in result
        assert settings_module.DEFAULT_HELP_DESK_EMAIL in result["output"]

    def test_lets_the_flow_continue_when_the_message_passes(self):
        cat = make_cat()
        incoming = {}

        assert send(cat, "How do I activate the VPN?", incoming) is incoming

    def test_records_the_verdict_when_it_blocks(self):
        # Not needed to answer, but it is the trace of why the turn was refused.
        cat = make_cat()
        send(cat, "a" * 5000)
        assert verdict_of(cat) == checks.VERDICT_MESSAGE_TOO_LONG

    def test_leaves_no_verdict_when_the_message_passes(self):
        cat = make_cat()
        send(cat, "How do I activate the VPN?")
        assert verdict_of(cat) is None

    def test_verdict_is_reset_between_turns(self):
        # Working memory lives for the whole session: a stale verdict would keep
        # blocking every later message of the same conversation.
        cat = make_cat()
        send(cat, "a" * 5000)
        assert verdict_of(cat) == checks.VERDICT_MESSAGE_TOO_LONG

        send(cat, "How do I activate the VPN?")
        assert verdict_of(cat) is None

    def test_replaces_a_reply_another_plugin_already_set(self):
        # This is what independence means in practice: whatever Rate Limiter
        # decided about a long message, our reply is the one delivered.
        cat = make_cat()

        result = send(cat, "a" * 5000, {"output": "Your account has been suspended."})

        assert result["output"] != "Your account has been suspended."
        assert settings_module.DEFAULT_HELP_DESK_EMAIL in result["output"]

    def test_keeps_a_reply_another_plugin_set_when_our_check_passes(self):
        # The mirror case, just as important: a rate-limit block on a short
        # message must still reach the user, so a passing check changes nothing.
        cat = make_cat()
        foreign = {"output": "You have sent too many messages."}

        assert send(cat, "How do I activate the VPN?", foreign) == foreign

    def test_a_missing_message_does_not_raise(self):
        # `fast_reply` also runs on turns where working memory holds no message.
        cat = make_cat()
        assert "output" not in guard_input_message({}, cat)


class TestDispatchFastReply:
    """The post-recall path, used by the evidence gate of Fase 3."""

    def test_returns_a_static_reply_when_a_verdict_is_set(self):
        cat = make_cat()
        setattr(
            cat.working_memory,
            guards.VERDICT_ATTRIBUTE,
            checks.VERDICT_MESSAGE_TOO_LONG,
        )

        result = dispatch_fast_reply({}, cat)

        assert "output" in result
        assert settings_module.DEFAULT_HELP_DESK_EMAIL in result["output"]

    def test_lets_the_normal_flow_continue_when_no_verdict_is_set(self):
        cat = make_cat()
        setattr(cat.working_memory, guards.VERDICT_ATTRIBUTE, None)

        assert "output" not in dispatch_fast_reply({}, cat)

    def test_lets_the_normal_flow_continue_when_the_attribute_is_absent(self):
        # The usual case now: the input guard answers on its own, so nothing
        # sets a verdict before the recall.
        assert "output" not in dispatch_fast_reply({}, make_cat())

    def test_falls_back_to_normal_flow_on_a_verdict_with_no_reply(self):
        # Better an answer from the model than an empty message to the user.
        cat = make_cat()
        setattr(cat.working_memory, guards.VERDICT_ATTRIBUTE, "verdict_never_defined")

        assert "output" not in dispatch_fast_reply({}, cat)


class TestConfiguration:
    def test_reply_for_returns_the_configured_reply_for_a_known_verdict(self):
        settings = settings_module.IctSiteRagGuardsSettings(
            help_desk_email="ict@example.org",
            message_too_long="Write to {help_desk_email}.",
        )

        assert guards.reply_for(checks.VERDICT_MESSAGE_TOO_LONG, settings) == (
            "Write to ict@example.org."
        )

    def test_reply_for_returns_none_for_an_unknown_verdict(self):
        settings = settings_module.IctSiteRagGuardsSettings()

        assert guards.reply_for("unknown_verdict", settings) is None

    def test_configured_limit_is_honoured(self):
        cat = make_cat({"max_message_chars": 10})
        assert "output" in send(cat, "a" * 11)

    def test_zero_disables_the_length_check(self):
        cat = make_cat({"max_message_chars": 0})
        assert "output" not in send(cat, "a" * 100_000)

    def test_configured_email_is_inserted_in_the_reply(self):
        cat = make_cat({"help_desk_email": "ict@example.org", "max_message_chars": 10})

        output = send(cat, "a" * 11)["output"]

        assert "ict@example.org" in output
        # No placeholder must survive into what the user reads.
        assert "{help_desk_email}" not in output

    def test_configured_reply_text_is_used(self):
        cat = make_cat(
            {
                "max_message_chars": 10,
                "message_too_long": "Too long. Write to {help_desk_email}.",
                "help_desk_email": "ict@example.org",
            }
        )

        assert send(cat, "a" * 11)["output"] == "Too long. Write to ict@example.org."

    def test_braces_in_a_hand_edited_reply_do_not_raise(self):
        # The text is edited in the admin panel: a stray brace must not turn a
        # reply into an exception, which is why rendering is a plain replace.
        cat = make_cat(
            {"max_message_chars": 10, "message_too_long": "Too long {oops} {}."}
        )

        assert send(cat, "a" * 11)["output"] == "Too long {oops} {}."

    def test_empty_stored_settings_fall_back_to_defaults(self):
        # settings.json is returned verbatim by the core, so "{}" must not mean
        # "no limit": that would silently disable the guard.
        cat = make_cat({})
        assert "output" in send(cat, "a" * 5000)

    def test_partial_stored_settings_keep_the_other_defaults(self):
        cat = make_cat({"help_desk_email": "ict@example.org"})
        assert guards.load_settings(cat).max_message_chars == (
            checks.DEFAULT_MAX_MESSAGE_CHARS
        )

    def test_invalid_stored_settings_fall_back_to_defaults(self):
        cat = make_cat({"max_message_chars": -5})
        assert guards.load_settings(cat).max_message_chars == (
            checks.DEFAULT_MAX_MESSAGE_CHARS
        )

    def test_wrong_type_in_stored_settings_falls_back_to_defaults(self):
        cat = make_cat({"max_message_chars": "a lot"})
        assert guards.load_settings(cat).max_message_chars == (
            checks.DEFAULT_MAX_MESSAGE_CHARS
        )

    def test_extra_stored_fields_are_ignored_when_the_settings_are_valid(self):
        cat = make_cat(
            {
                "help_desk_email": "ict@example.org",
                "max_message_chars": 123,
                "extra_field": "ignored",
            }
        )

        loaded = guards.load_settings(cat)

        assert loaded.help_desk_email == "ict@example.org"
        assert loaded.max_message_chars == 123

    def test_unavailable_settings_fall_back_to_defaults(self):
        # A fake cat with no plugin registry, the situation in most of the tests.
        assert guards.load_settings(make_cat()).max_message_chars == (
            checks.DEFAULT_MAX_MESSAGE_CHARS
        )

    def test_unavailable_settings_fall_back_to_the_shipped_help_desk_address(self):
        assert (
            guards.load_settings(make_cat()).help_desk_email
            == settings_module.DEFAULT_HELP_DESK_EMAIL
            == "helpdesk@example.org"
        )


class TestSettingsModel:
    def test_every_verdict_has_a_reply_setting(self):
        # Adding a check without its reply would silently fall back to the
        # model, defeating the guard. This fails the moment that happens.
        declared = {
            value
            for name, value in vars(checks).items()
            if name.startswith("VERDICT_")
        }
        missing = declared - set(guards.REPLY_SETTING_BY_VERDICT)
        assert not missing, f"verdicts without a reply setting: {sorted(missing)}"

    def test_every_reply_setting_exists_on_the_model(self):
        fields = settings_module.IctSiteRagGuardsSettings.model_fields
        for verdict, setting_name in guards.REPLY_SETTING_BY_VERDICT.items():
            assert setting_name in fields, (
                f"verdict '{verdict}' points at '{setting_name}', "
                "which is not a settings field"
            )

    def test_default_replies_are_bilingual(self):
        # Until language detection exists, each reply carries both languages.
        defaults = settings_module.IctSiteRagGuardsSettings()
        for setting_name in guards.REPLY_SETTING_BY_VERDICT.values():
            assert "\n\n" in getattr(defaults, setting_name)

    def test_model_defaults_can_build_settings_json(self):
        # The core creates settings.json from the model: a field without a
        # default would make activation fail.
        assert settings_module.IctSiteRagGuardsSettings().model_dump_json()

    @pytest.mark.parametrize(
        "bad_email", ["not-an-address", "@example.org", "ict@", " "]
    )
    def test_email_must_look_like_an_address(self, bad_email):
        with pytest.raises(ValueError):
            settings_module.IctSiteRagGuardsSettings(help_desk_email=bad_email)

    def test_reply_cannot_be_empty(self):
        with pytest.raises(ValueError):
            settings_module.IctSiteRagGuardsSettings(message_too_long="   ")

    def test_negative_limit_is_rejected(self):
        with pytest.raises(ValueError):
            settings_module.IctSiteRagGuardsSettings(max_message_chars=-1)
