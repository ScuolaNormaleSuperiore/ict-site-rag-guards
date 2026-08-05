# Security Guards

This document explains the security-oriented guards currently implemented in
`ict-site-rag-guards`, with a detailed focus on the prompt injection guard
introduced in v1.

## Prompt Injection Guard v1

### Purpose

The prompt injection guard blocks user messages that try to alter the chatbot's
instructions, bypass its rules, or reveal hidden prompt material before the
request reaches retrieval or generation.

The guard runs on the Cheshire Cat `fast_reply` hook, so a blocked message:

- does not reach retrieval
- does not spend generation tokens
- is not written to episodic memory

This is the same early-stop path used by the existing length guard.

### Two-stage detection

The guard uses two independent detectors.

1. Custom detector

- implemented in `checks.py`
- conservative built-in IT/EN pattern set
- designed to catch explicit attempts such as:
  - ignoring previous instructions
  - bypassing rules or guardrails
  - revealing the system prompt or internal instructions

2. Local classifier

- implemented through `transformers.pipeline("text-classification", ...)`
- runs only if the custom detector does not block first
- uses the configured model and threshold

The combined logic is `OR`: one positive detector is enough to block.

### Execution flow

1. The plugin extracts the incoming text from working memory.
2. The normal deterministic input checks run.
3. If the prompt injection custom detector matches, the plugin returns the
   configured static reply immediately.
4. Otherwise, if the classifier is enabled, the plugin runs the configured
   local model.
5. If the classifier returns the configured injection label with score greater
   than or equal to the configured threshold, the plugin returns the same
   static reply immediately.
6. If neither detector trips, the message continues normally.

### Settings

The guard adds these admin settings:

- `Security guard: block explicit prompt injection patterns`
- `Security guard: block prompt injection with local classifier`
- `Security guard: prompt injection classifier model`
- `Security guard: prompt injection classifier threshold`
- `Security guard: Hugging Face token`
- `Security guard: reply — prompt injection detected`

The threshold is the minimum confidence required for the classifier to block a
message. Example:

- classifier output: `label=MALICIOUS`, `score=0.91`
- threshold: `0.85`
- result: block

If the score were `0.62`, the same label would not block with that threshold.

### Supported models in v1

- `meta-llama/Llama-Prompt-Guard-2-86M`
- `meta-llama/Llama-Prompt-Guard-2-22M`
- `deepset/deberta-v3-base-injection`

The default is `meta-llama/Llama-Prompt-Guard-2-86M`, chosen because this
project needs both Italian and English support.

The three supported models do not have the same access profile:

- `deepset/deberta-v3-base-injection` is public and can be used without a
  Hugging Face token
- the two `meta-llama/*` models are gated and require both approved access on
  Hugging Face and an authenticated token at runtime

### Hugging Face token handling

The plugin supports two ways to provide a token for gated models:

1. `HF_TOKEN` environment variable
2. `Security guard: Hugging Face token` in the plugin admin settings

If both are present, `HF_TOKEN` takes precedence.

This is deliberate:

- deployments that already manage secrets outside the plugin can keep doing so
- installations that prefer a plugin-local configuration can still use the
  admin setting

The token is used only to load gated classifier models. Public models do not
need it.

Operationally:

- no token is required for `deepset/deberta-v3-base-injection`
- a valid token plus approved model access are required for the two Meta models
- if a gated model is selected without valid access, the classifier goes
  `fail-open`, logs a warning, and the message continues normally

### Error policy

The classifier is `fail-open`.

If model loading, dependency import, or inference fails:

- the message is not blocked by the classifier
- the flow continues normally
- the plugin logs a warning

This keeps the chatbot available even when the classifier runtime is not.

### Dependency model

The classifier introduces explicit runtime dependencies declared in
`requirements.txt`.

This is intentional. The plugin must not depend on libraries that happen to be
installed only because another plugin shares the same Cheshire Cat instance.

### Logging and measurement

The guard logs the minimum information needed to evaluate effectiveness and
latency without logging the original message text.

Whether the guard is active at all is announced separately, once when the plugin
starts guarding and again on every configuration change, never per message. The
`security(...)` part of that line reports which mechanisms are on, with the
model and threshold in use; with both mechanisms off it becomes a `WARNING`
naming `security` as uncovered. This matters because a disabled guard is
otherwise indistinguishable, in the log, from a guard that finds nothing.

A message that passes writes one line at `DEBUG` only, listing the checks that
covered the turn — `injection_patterns`, `injection_classifier` — and the
latency. At the default `INFO` level a clean conversation stays silent.

When a block happens, the logs identify at least:

- the guard category, `security`, and the verdict, `prompt_injection`
- whether the detector was `custom` or `classifier`
- which of the built-in patterns matched, by name, if the custom detector blocked
- the selected model, if the classifier blocked
- the classifier score and threshold, if applicable
- the classifier latency in milliseconds, when measured

The pattern name is what makes a false positive diagnosable: since the refused
text is deliberately never logged, without it the line holds nothing to reason
from. The names are therefore part of the log contract — renaming one is a
breaking change for whoever greps these lines.

During model loading, the runtime also logs, at `INFO`:

- when the plugin starts loading a classifier model into memory
- when model loading succeeds
- when model loading fails, as a warning

A pipeline found already cached in memory is logged at `DEBUG`, not `INFO`: it
happens on every message that reaches the classifier, and at `INFO` it buries
the lines that record an actual decision.

Those messages are intentionally phrased in terms of the plugin's own state.
With a plain `transformers.pipeline(...)` call, the plugin can reliably know
whether the model was already cached in memory, but it cannot always prove
whether the underlying files were freshly downloaded from Hugging Face or read
from the local Hugging Face disk cache.

### Limits of v1

This first version is intentionally narrow.

- The custom detector is conservative and catches explicit attempts only.
- The classifier is local and model-based, but its real precision on this ICT
  corpus must be measured rather than assumed.
- The guard covers direct prompt injection on the user message, not indirect
  prompt injection through retrieved documents.
- Different thresholds per model, GPU selection, and structured telemetry are
  outside the scope of v1.
