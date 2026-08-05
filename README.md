# ICT Site RAG Guards

`ICT Site RAG Guards` is a Cheshire Cat AI plugin for website-based ICT support chatbots.

It adds deterministic and configurable guardrails around the normal RAG flow so that risky or invalid requests can be stopped early, before they reach retrieval or generation.

## Features

- Input guardrails for message validation before generation
- Static fallback replies for blocked requests
- Admin-configurable settings from the Cheshire Cat plugin panel
- Testable split between pure decision logic and Cheshire Cat hook adapters
- Architecture prepared for future RAG evidence checks and output guardrails

## Current Status

The plugin is work in progress.

Currently implemented:

- maximum input length check
- prompt injection guard with a built-in detector plus an optional local classifier
- configurable Help Desk email
- configurable fallback message for over-long requests

Planned next steps include additional input checks, evidence sufficiency gating, prompt policy, output checks, and telemetry.

## Requirements

- Cheshire Cat AI `1.9.2` on the `1.x` line
- A website chatbot integration that sends user messages to Cheshire Cat AI

The plugin is self-contained: it requires no companion plugin, and every third-party dependency it needs is declared in its own `requirements.txt`, which Cheshire Cat AI installs on activation. It currently declares one, `phonenumberslite`, used to validate phone numbers against a numbering plan instead of matching them by shape.

Sharing an installation with other plugins is supported: when one of its own checks does not trigger, a reply another plugin has already produced is passed through untouched.

## Installation

1. Copy the plugin folder into the Cheshire Cat plugins directory.
2. Start or restart Cheshire Cat AI.
3. Open the Cheshire Cat admin panel.
4. Enable `ICT Site RAG Guards` from the plugins list.

## Configuration

After activation, open:

`Plugins -> ICT Site RAG Guards -> Settings`

Settings are named after the guard family they belong to, so related options
read together in the form:

- `Help Desk e-mail`
- `Limits guard: maximum message length (characters)`
- `Limits guard: reply — message too long`
- `Privacy guard: block e-mail addresses`
- `Privacy guard: block codice fiscale`
- `Privacy guard: block IBAN`
- `Privacy guard: block phone numbers`
- `Privacy guard: region for phone numbers written without a prefix`
- `Privacy guard: reply — personal data detected`
- `Security guard: block explicit prompt injection patterns`
- `Security guard: block prompt injection with local classifier`
- `Security guard: prompt injection classifier model`
- `Security guard: prompt injection classifier threshold`
- `Security guard: Hugging Face token`
- `Security guard: reply — prompt injection detected`

The shipped default Help Desk address is a placeholder and should be replaced for real deployments.

## How It Works

The current implementation uses Cheshire Cat hooks to inspect the incoming message before the normal agent flow continues.

If the message exceeds the configured length limit, the plugin returns a static reply immediately:

- no retrieval
- no LLM generation
- no episodic storage for that refused message

This behavior is implemented through a small hook layer in `ict_site_rag_guards.py` and pure decision logic in `checks.py`.

The same early-stop path is also used by the prompt injection guard. It first
applies a conservative built-in detector for explicit override or reveal
attempts, then optionally runs a local classifier. When either one trips, the
plugin returns a static reply before retrieval or generation. A detailed
description of the guard lives in `DOC/SecurityGuards.md`, including when a
Hugging Face token is needed for gated classifier models.

### What the log records

A guardrail that stops working raises no error: the chatbot simply keeps
answering unguarded. The log is what makes that visible, so it answers two
different questions.

**Which guards are active.** One line when the plugin starts guarding, and again
whenever the configuration changes — not on every message:

```
[ict-site-rag-guards] guards active: limits(max 1000 chars), privacy(email+codice_fiscale+iban+phone, region=IT), security(patterns+classifier meta-llama/Llama-Prompt-Guard-2-86M@0.85)
```

When a whole family is switched off, the same line is a `WARNING` and names what
is left uncovered, because that is the state in which the chatbot is exposed and
nothing else reports it:

```
[ict-site-rag-guards] guards active: limits(max 500 chars), privacy(disabled), security(patterns+classifier …); no guard covers: privacy
```

**Why a request was refused.** One `INFO` line per block, naming the guard that
stopped it, so a refusal can be told apart from a normal answer and from another
plugin's block:

```
[ict-site-rag-guards] input blocked, category='privacy', verdict='personal_data', detected=email+phone (mobile), latency_ms=0.14; no retrieval, no generation, nothing stored in memory
```

`category` is the guard family — `limits`, `privacy`, `security` — and is what
makes refusals countable per family. `verdict` is the control that tripped, and
the fields after it describe the violation: the length against the limit, which
detectors matched, or which injection pattern and classifier score fired.

Messages that pass write nothing at `INFO`. Set `CCAT_LOG_LEVEL=DEBUG` to get
one line per allowed message, which is the level to use when diagnosing a
specific request:

```
[ict-site-rag-guards] input allowed, checks=length+injection_patterns+personal_data+injection_classifier, latency_ms=0.03
```

The refused message itself is never logged, on any path. That is deliberate: on
the privacy guard it would defeat the check it is reporting. One consequence is
worth knowing, because no plugin can change it — Cheshire Cat itself logs every
incoming message before any plugin runs, so log retention remains a
data-protection question independent of this plugin.

## Development

Main files:

- `checks.py`: pure guard logic
- `settings.py`: plugin settings model and shipped defaults
- `ict_site_rag_guards.py`: Cheshire Cat hooks and settings loading
- `tests/`: the test suite, described in [DOC/TESTING.md](DOC/TESTING.md)

Project-specific architecture notes, roadmap, and development guidance live under `DEV/AGENTS/` and `DEV/TODO/`.

## Testing

Run unit tests only:

```bash
python run-tests.py --unit
```

Run the full suite:

```bash
python run-tests.py
```

These are the only two commands needed to run the tests. Everything else about testing — the test layout, which tests need the Cheshire Cat container, how the runner behaves, and what is verified manually — is in [DOC/TESTING.md](DOC/TESTING.md).

## Packaging

Build the distributable zip with:

```bash
python package-plugin.py
```

When a new file must be shipped with the plugin, update `package-plugin.py` so the release package stays explicit and complete.

## License

GPL-3.0-only. See `LICENSE`.
