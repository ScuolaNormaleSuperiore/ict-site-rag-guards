# RAG Guards


`RAG Guards` is a Cheshire Cat AI plugin for website-based ICT support chatbots.

It adds deterministic and configurable guardrails around the normal RAG flow so that risky or invalid requests can be stopped early, before they reach retrieval or generation.

The plugin ships **no model weights**. Its prompt-injection guard can be configured to run `meta-llama/Llama-Prompt-Guard-2-86M`, which is downloaded at runtime from Hugging Face by whoever installs the plugin, under Meta's own terms. The attribution that licence requires, and the licence of every model this plugin can run, are in [License and Legal Notes](#license-and-legal-notes).

## Features

- Input guardrails for message validation before generation
- Output guardrail for personal-data leakage before delivery
- Static fallback replies for blocked requests
- Admin-configurable settings from the Cheshire Cat plugin panel
- Testable split between pure decision logic and Cheshire Cat hook adapters
- Architecture prepared for future RAG evidence checks and output guardrails
- Optional use of Llama classifiers.

## Current Status

The plugin is work in progress.

Currently implemented:

- maximum input length check
- personal-data guard for e-mail, codice fiscale, IBAN and phone numbers
- output personal-data guard on generated replies
- prompt injection guard with a built-in detector plus an optional local classifier
- offensive-input guard with a local multilingual classifier, shipped switched off
- configurable Help Desk email
- configurable static replies for over-long requests, personal data, output personal data, prompt injection and offensive content

Planned next steps include prompt policy, further output checks, and telemetry.

The naming of guards is documented in [DOC/GuardTaxonomy.md](DOC/GuardTaxonomy.md). The plugin keeps three axes separate:

- `stage`: where the control acts
- `category`: what kind of risk it addresses
- `verdict`: which specific control fired

## Requirements

- Cheshire Cat AI `1.9.2` on the `1.x` line
- A website chatbot integration that sends user messages to Cheshire Cat AI

The plugin is self-contained: it requires no companion plugin, and every third-party dependency it needs is declared in its own `requirements.txt`, which Cheshire Cat AI installs on activation. It currently declares `phonenumberslite` for phone-number validation and `transformers` plus `torch` for the optional local prompt-injection classifier.

Sharing an installation with other plugins is supported: when one of its own checks does not trigger, a reply another plugin has already produced is passed through untouched.

## Installation

1. Copy the plugin folder into the Cheshire Cat plugins directory.
2. Start or restart Cheshire Cat AI.
3. Open the Cheshire Cat admin panel.
4. Enable `RAG Guards` from the plugins list.

## Configuration

After activation, open:

`Plugins -> RAG Guards -> Settings`

Settings are named after the guard family they belong to, so related options
read together in the form:

- `Help Desk e-mail`
- `Limits guard: maximum message length (characters)`
- `Limits guard: reply — message too long`
- `Input privacy guard: block e-mail addresses`
- `Input privacy guard: block codice fiscale`
- `Input privacy guard: block IBAN`
- `Input privacy guard: block phone numbers`
- `Input privacy guard: region for phone numbers written without a prefix`
- `Input privacy guard: reply — personal data detected`
- `Output privacy guard: block e-mail addresses`
- `Output privacy guard: block codice fiscale`
- `Output privacy guard: block IBAN`
- `Output privacy guard: block phone numbers`
- `Output privacy guard: region for phone numbers written without a prefix`
- `Output privacy guard: reply — outgoing personal data detected`
- `Security guard: block explicit prompt injection patterns`
- `Security guard: block prompt injection with local classifier`
- `Security guard: prompt injection classifier model`
- `Security guard: prompt injection classifier threshold`
- `Security guard: Hugging Face token`
- `Security guard: reply — prompt injection detected`
- `Tone guard: block offensive incoming messages with local classifier`
- `Tone guard: offensive input classifier model`
- `Tone guard: offensive input classifier threshold`
- `Tone guard: reply — offensive content detected`

One setting is shipped **switched off**, and it is the only one:
`Tone guard: block offensive incoming messages with local classifier`. It loads a
second model into memory and adds one inference to every message that reaches it,
and its precision on real help-desk traffic still has to be measured, so enabling
it is an explicit decision. Everything else ships enabled.

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

A further input check refuses offensive or violent messages, on the same
early-stop path and with a local multilingual classifier. It runs **last**, so it
only sees a message every other check let through, and one consequence is
deliberate: a message that is both offensive and a prompt-injection attempt is
reported as prompt injection, because an attack on the assistant is the more
pertinent correction to give back. Two things set it apart from the other guards.
Its threshold is compared against the **sum** of the classes that count as
offensive for the selected model, not against a single score, so the same number
means something stricter here than in the prompt injection guard. And it is the
**only check shipped switched off**, because it loads a second model into memory
and its precision on real help-desk traffic still has to be measured. A detailed
description lives in `DOC/ToneGuards.md`.

The plugin also inspects the generated answer just before delivery. If the
reply contains personal data, it is replaced with a static fallback instead of
being sent to the user. The input-side and output-side privacy guards now have
separate detector settings, so an installation can choose to block personal
data on input, on output, on both, or on neither. Both sides use the same
detector family — e-mail, phone numbers, codice fiscale and IBAN — but they
have distinct configuration, verdicts and reply texts because they act at
different points of the flow. A detailed description of the current output-side
behavior lives in `DOC/OutputGuards.md`.

### What the log records

A guardrail that stops working raises no error: the chatbot simply keeps
answering unguarded. The log is what makes that visible, so it answers two
different questions.

**Which guards are active.** One line when the plugin starts guarding, and again
whenever the configuration changes — not on every message:

```
[ict-site-rag-guards] guards active: limits(max 1000 chars), privacy(input=email+codice_fiscale+iban+phone, input_region=IT, output=email, output_region=IT), security(patterns+classifier meta-llama/Llama-Prompt-Guard-2-86M@0.85), tone(disabled)
```

When a whole family is switched off, the same line is a `WARNING` and names what
is left uncovered, because that is the state in which the chatbot is exposed and
nothing else reports it:

```
[ict-site-rag-guards] guards active: limits(max 500 chars), privacy(disabled), security(patterns+classifier …), tone(disabled); no guard covers: privacy
```

`tone(disabled)` is in both examples and in neither warning, which is deliberate.
The `no guard covers` field answers the narrower question «was a protection this
plugin provides by default switched off», and the tone guard ships off. A
`WARNING` on every fresh installation would teach everyone to skip this line,
including on the day privacy really is disabled — so the state is reported in the
text and does not raise the severity. Once the tone guard is enabled and its
model fails to load, that *is* a warning, because then the category is uncovered
without anyone having chosen it.

**Why a request was refused.** One `INFO` line per block, naming the guard that
stopped it, so a refusal can be told apart from a normal answer and from another
plugin's block:

```
[ict-site-rag-guards] input blocked, stage='input', category='privacy', verdict='personal_data', detected=email+phone (mobile), latency_ms=0.14; no retrieval, no generation, nothing stored in memory
```

For the current output guard:

```
[ict-site-rag-guards] output blocked, stage='output', category='privacy', verdict='output_personal_data', detected=email; generated reply replaced before delivery
```

And for the offensive-input guard, when it is enabled:

```
[ict-site-rag-guards] input blocked, stage='input', category='tone', verdict='offensive_input', detector=classifier, model=IMSyPP/hate_speech_multilingual, label=violent, score=0.999, threshold=0.60, latency_ms=79.2; no retrieval, no generation, nothing stored in memory
```

`stage`, `category`, and `verdict` are three separate fields by design:

- `stage` says where the guard acted, currently `input` or `output`
- `category` says the guard family — `limits`, `privacy`, `security`, `tone`
- `verdict` says the specific control that tripped

The fields after them describe the violation: the length against the limit,
which detectors matched, or which injection pattern and classifier score fired.

On the offensive-input line, `score` needs one caution: it is the **sum** of the
classes that count as offensive for that model, not the score of the single class
named in `label`. Those classes are mutually exclusive, so a message can be split
between them and be certainly offensive without any one of them being high. That
is why this guard's threshold is lower than the prompt-injection one — the two
numbers do not measure the same thing.

A message that passes writes no *verdict* line: the guards stay silent when they
find nothing. Set `CCAT_LOG_LEVEL=DEBUG` to get one line per allowed message,
which is the level to use when diagnosing a specific request:

```
[ict-site-rag-guards] input allowed, stage='input', checks=length+injection_patterns+personal_data+injection_classifier, latency_ms=0.03
```

One exception at `INFO`, while the prompt-injection classifier is being
evaluated: it reports reusing its in-memory pipeline, so with the classifier
enabled a clean message does produce one line. Disable the classifier, or wait
for that line to be demoted to `DEBUG`, if a silent `INFO` log matters more than
observing model reuse.

The refused message itself is never logged, on any path. That is deliberate: on
the privacy guard it would defeat the check it is reporting. One consequence is
worth knowing, because no plugin can change it — Cheshire Cat itself logs every
incoming message before any plugin runs, so log retention remains a
data-protection question independent of this plugin.

## Development

Main files:

- `checks.py`: pure guard logic
- `classifier_runtime.py`: machinery shared by the local models — pipeline cache, negative cache on failed loads, fail-open contract
- `prompt_injection_classifier.py`: one expected label against a threshold
- `offensive_input_classifier.py`: the sum of a model's offensive classes against a threshold
- `settings.py`: plugin settings model and shipped defaults
- `ict_site_rag_guards.py`: Cheshire Cat hooks and settings loading
- `tests/`: the test suite, described in [DOC/TestingCode.md](DOC/TestingCode.md)

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

These are the only two commands needed to run the tests. Everything else about testing — the test layout, which tests need the Cheshire Cat container, how the runner behaves, and what is verified manually — is in [DOC/TestingCode.md](DOC/TestingCode.md).

## Packaging

Build the distributable zip with:

```bash
python package-plugin.py
```

When a new file must be shipped with the plugin, update `package-plugin.py` so the release package stays explicit and complete.

## License and Legal Notes

### The plugin

The code in this repository is released under **GNU General Public License v3.0 only**. See `LICENSE`.

### The models are not part of it

This plugin distributes **no model weights**. The release package contains ten files — Python modules, `plugin.json`, `README.md`, `LICENSE`, `requirements.txt` — and nothing else. Every classifier model is downloaded at runtime, from Hugging Face, by the person who installs and configures the plugin, and each one carries its own licence which that person accepts directly with its publisher.

That separation is what keeps the arrangement clean. The GPL governs this code; it does not and cannot govern weights it never ships. **Never add model weights to the release package**: some of the models below are distributed under licences that impose use restrictions, and GPLv3 section 10 forbids adding restrictions to conveyed material — bundling them would create a genuine incompatibility where today there is none.

### Built with Llama

The prompt-injection guard can be configured to run Meta's Llama Prompt Guard 2. When it is, the following notice applies:

> **Llama is licensed under the Llama Community License, Copyright © Meta Platforms, Inc. All Rights Reserved.**

The applicable version, read from the model card on 2026-08-06, is the **Llama 4 Community License Agreement** (`license_name: llama4`). Both Meta models are **gated**: access is granted manually by Meta after the request is accepted, so using them requires accepting Meta's terms on the model page and authenticating at runtime. See [DOC/SecurityGuards.md](DOC/SecurityGuards.md) for the operational steps.

### Licence of each supported model

Verified against the Hugging Face model cards on 2026-08-06. Check them again before a release: a publisher can change a licence, and this table is a snapshot rather than a promise.

| Model | Guard | Licence | Gated |
| --- | --- | --- | --- |
| `meta-llama/Llama-Prompt-Guard-2-86M` | prompt injection, **shipped default** | Llama 4 Community License | yes, manual approval |
| `meta-llama/Llama-Prompt-Guard-2-22M` | prompt injection | Llama 4 Community License | yes, manual approval |
| `deepset/deberta-v3-base-injection` | prompt injection | MIT | no |
| `IMSyPP/hate_speech_multilingual` | offensive input, **shipped default** | MIT | no |
| `patriciacarla/HS-multilingual-DNR` | offensive input | Apache-2.0 | no |
| `textdetox/bert-multilingual-toxicity-classifier` | offensive input | OpenRAIL++ | no |

Two entries deserve attention before you enable them:

- **The two Meta models are not free software.** The Llama Community License is not an open-source licence: it carries an acceptable-use policy, a monthly-active-users clause and naming requirements. Nothing about that conflicts with this plugin's GPLv3 as long as the weights stay out of the package, but an installation that enables them has accepted terms the GPL does not grant.
- **`textdetox/bert-multilingual-toxicity-classifier` is OpenRAIL++**, which permits redistribution but attaches behavioural use restrictions that must be passed on downstream. It is the only offensive-input model of the three that is not plainly permissive.

The two shipped defaults sit on opposite sides of this: the tone guard defaults to an MIT model, the prompt-injection guard defaults to a gated Meta one. If a deployment needs to avoid non-free licences entirely, both guards have a permissive option — `deepset/deberta-v3-base-injection` (MIT) and the default `IMSyPP/hate_speech_multilingual` (MIT) — selectable from the admin panel with no code change.

### Runtime dependencies

Declared in `requirements.txt`, all GPL-compatible: `phonenumberslite` (Apache-2.0), `transformers` (Apache-2.0), `torch` (BSD-3-Clause).
