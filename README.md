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

Available settings:

- `Help Desk email`
- `Maximum message length (characters)`
- `Reply: message too long`
- `Security guard: block explicit prompt injection patterns`
- `Security guard: block prompt injection with local classifier`
- `Security guard: prompt injection classifier model`
- `Security guard: prompt injection classifier threshold`
- `Security guard: Hugging Face token`
- `Reply: prompt injection detected`

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
description of the guard lives in `DOC/SucurityGuards.md`, including when a
Hugging Face token is needed for gated classifier models.

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
