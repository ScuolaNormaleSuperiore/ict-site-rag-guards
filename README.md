# ict-site-rag-guards

A single, modular Cheshire Cat AI plugin that adds input/output guardrails, RAG evidence gating, and token-budget controls to the Scuola Normale Superiore ICT chatbot, keeping the ordinary flow to one LLM call and escalating to an LLM judge only when risk or uncertainty justifies it.

## Status

Partly implemented. Roadmap step 1 — the input length guard — is built, configurable from the admin panel, covered by automated tests, and verified on a running Cheshire Cat AI 1.9.2 instance. The hooks listed below were checked against that installation and exist with the names shown.

Everything else remains a proposal: the modules still to be built, the thresholds, and the token budgets are starting points, not approved requirements.

## Documentation baseline

This project must follow the Stregatto / Cheshire Cat AI v1 documentation:

- `https://cheshire-cat-ai.github.io/docs/1/`

Do not assume Cheshire Cat AI v2 behavior or APIs when designing or implementing this plugin.

## Scope

- Informational, first-level assistant answering questions about SNS ICT services, based exclusively on official public sources.
- Anonymous access to the full public knowledge base; authentication is only used for authorized personalization.
- Italian and English supported from the first version.
- Out of scope for this version: ticketing, email, operational escalation, MCP, and system-level operations.
- "Correctness" is not automatically certifiable; the realistic control is groundedness of the answer in the retrieved sources.

## Why one plugin

The controls are not independent — they act in sequence on the same Working Memory (input guard → RAG query → evidence gate → prompt → output guard). A single plugin avoids hook-ordering conflicts between separate plugins, centralizes configuration, and lets the whole pipeline be tested as one unit. Internally, the plugin stays modular (see below).

## Architecture

The WordPress plugin remains the presentation channel. Cheshire Cat AI handles session, working memory, vector search, and the LLM call. `ict-site-rag-guards` hooks into the critical points and applies checks, thresholds, and fallback responses.

| Stage | Purpose |
| --- | --- |
| 1. Reception | Message plus minimal technical session data and authorized attributes only. |
| 2. Input guard | Basic privacy, language, abuse, length, and obvious prompt-injection checks. |
| 3. RAG query prep | Normalize the question; select language/metadata filters. |
| 4. Retrieval | Search declarative memory with controlled `k` and similarity threshold. |
| 5. Evidence gate | Deduplicate, discard weak matches, stop early if evidence is insufficient. |
| 6. Prompt + LLM | One LLM call with a compact prompt, limited history, minimal steps. |
| 7. Output guard | Local checks; LLM judge only for at-risk cases. |
| 8. Response | Answer with sources, or a cautious fallback / clarification request. |
| 9. Feedback | Ratings and allowed metrics, kept separate from personal attributes. |

## Modules

| Module | Responsibility | Key configuration |
| --- | --- | --- |
| `input_guard` | Initial validation, block/continue decision | length limits, PII patterns, language, lists, standard messages |
| `rag_policy` | Query normalization, memory filters | `k`, similarity threshold, language/type/source metadata |
| `evidence_gate` | Deduplication, sufficiency check | min. documents, score, diversity, token budget |
| `prompt_policy` | Instructions and context composition | short prompt, history window, citation format |
| `output_guard` | PII, tone, groundedness, fallback | rules, judge trigger conditions, allowed outcomes |
| `session_policy` | Ephemeral attributes, conversational memory | TTL, turn count, persistence exclusions |
| `telemetry` | Minimized technical/qualitative metrics | latency, tokens, RAG outcome, fallback rate, feedback |

These are responsibilities, not files. Today only `input_guard` exists, realized as the decision logic in `checks.py` plus the hooks in `ict_site_rag_guards.py`; the other modules are not built yet. For the files actually in the repository see *Testing → Code layout*.

## Cheshire Cat AI hooks used

| Hook | Used by |
| --- | --- |
| `fast_reply` | `input_guard` (implemented, priority `-1`) |
| `cat_recall_query` | `rag_policy` |
| `before_cat_recalls_declarative_memories` | `rag_policy` |
| `after_cat_recalls_memories` / `agent_fast_reply` | `evidence_gate` |
| `before_agent_starts` (prompt hooks) | `prompt_policy` |
| `before_cat_sends_message` | `output_guard`, `session_policy` |
| `before_cat_stores_episodic_memory` | `session_policy` |
| `agent_allowed_tools = []` | `rag_policy` (tools disabled in v1) |

All of these exist in the installed Cheshire Cat AI 1.9.2 with the names above. Re-verify after a core upgrade: the public docs may describe a later revision.

### Why input checks run on `fast_reply`

`fast_reply` and `agent_fast_reply` are both shortcuts, but they sit at opposite ends of the turn. `fast_reply` runs before anything else; `agent_fast_reply` runs after the recall, inside the agent.

| | `fast_reply` | `agent_fast_reply` |
| --- | --- | --- |
| Retrieval performed | no | yes |
| User message written to the vector database | **no** | **yes** |
| Message in conversation history | no | yes |
| `before_cat_sends_message` runs | no | yes |
| `why` metadata populated | no | yes |

Input checks — length, and later personal data, language, injection — use `fast_reply`, for two reasons.

**A refused message must not be persisted.** On the `agent_fast_reply` path the core stores the user message in episodic memory after the agent returns, so a message blocked *for containing personal data* would be written to the vector database anyway. `before_cat_stores_episodic_memory` cannot fully undo it: the stored text and metadata can be rewritten, but the embedding is computed from the original text.

**The check must not depend on other plugins.** Hooks sharing a name are piped in descending priority order, not short-circuited, and the last non-`None` return wins. This plugin registers at priority `-1`, below the default `1` other plugins get, so its reply is the one delivered whatever the `Rate Limiter` plugin decided about the same message. When a check passes, the received value is returned untouched, so another plugin's block — a rate limit, for instance — still reaches the user.

What this does *not* control is another plugin's side effects: Rate Limiter still records its infraction and applies its progressive suspension. Only setting its own `max_prompt_length` to `0` prevents that.

`agent_fast_reply` remains the dispatch point for verdicts that can only be formed after the recall, the evidence gate of Fase 3 above all. There a reply does go through the output guard and the history, and the retrieval has already happened out of necessity.

Two more details from the same check, useful when adding hooks:

- Hooks are dispatched by name, and `@hook` accepts an explicit one, so a plugin function can keep a descriptive name: `@hook("fast_reply", priority=-1) def guard_input_message(...)`.
- The `@hook` decorator replaces the function with a `CatHook` object, which is not callable. Tests reach the real function through `.function`.

## Token budget targets (to be validated)

- Fixed prompt: 250–400 tokens
- History: max 600–800 tokens, or last 2–4 relevant turns
- RAG context: 800–1,200 tokens, starting `k=4`
- Answer: 250–400 tokens (longer only for genuinely long procedures)
- Judge LLM activation: target under 15% of responses
- No-evidence requests: rule-based fallback, zero generative tokens

## Decision rules

| Condition | Outcome |
| --- | --- |
| Invalid input or obvious PII | Stop before RAG; ask to rephrase without personal data |
| Ambiguous question | Short clarification request |
| No document above threshold | Stop before LLM; insufficiency message + Help Desk pointer |
| Sufficient evidence | Generate short answer with source references |
| Suspicious but recoverable output | Judge evaluation or cautious replacement |
| Conflicting sources | No arbitration; flag conflict, request human review |

## Configuration

Everything an administrator can change lives in the Cheshire Cat admin panel, under *Plugins → ICT Site RAG Guards → Settings*. Nothing has to be edited in the code to tune the plugin.

| Setting | Initial value | What it does |
| --- | --- | --- |
| Help Desk email | `helpdesk@mysite.org` | Address offered when a request cannot be answered. Insert it in any reply with `{help_desk_email}` |
| Maximum message length | `1000` characters | Longer messages get a static reply without reaching the model, so they cost no generation tokens. `0` disables the check |
| Reply: message too long | bilingual text | Sent when the limit is exceeded |

### Where the values come from

`settings.json`, in the plugin folder, holds the configuration of one installation. It is **not** in version control: the core creates it from the defaults declared in `settings.py` the first time the plugin is activated, so a fresh install never inherits anyone else's configuration.

That makes the defaults in `settings.py` the configuration the plugin ships with, not placeholders that someone will notice later. Two of them need a decision before any real deployment:

- **`helpdesk@mysite.org` is deliberately a dummy address.** It is shown verbatim to users on any installation where nobody opens the admin panel. Replace it there, or change the default before distributing.
- **The `1000` character limit interacts with other plugins.** Keep it below the `max_prompt_length` of the `Rate Limiter` plugin, if that one is installed: its checks run earlier in the flow, so a lower limit there means this plugin never gets to answer. See *What is not automated* below and `DEV/ISSUES_TODO.md`.

### Reading the settings is failure-tolerant

The core returns `settings.json` verbatim, without filling in anything. A missing or partial file would therefore yield no threshold at all, silently disabling the guard. To prevent that, every read is validated through the settings model, which supplies the default of any absent field. The consequence in practice: a new setting added in a future version works immediately on an existing installation, but its field shows up empty in the admin form until the form is saved once.

## Testing

Guardrails fail silently: when a control stops working the chatbot does not raise an error, it just keeps answering unguarded. Tests are how that stays visible.

### Code layout

| File | Contents | Needs the core? |
| --- | --- | --- |
| `checks.py` | All decision logic: thresholds, verdicts, rules. Imports nothing from `cat` | No |
| `settings.py` | The settings model the admin form is built from, and the shipped defaults | Yes |
| `ict_site_rag_guards.py` | The hooks only: read from the Cat, delegate to `checks`, write back | Yes |
| `tests/unit/` | Pure logic and shipped metadata. Plain `pytest`, no Cheshire Cat at all | No |
| `tests/integration/` | Hook wiring and configuration, against a fake `cat` object | Yes |

The test folders are the classification: what goes in `tests/unit/` must import nothing from `cat`, and a file that breaks that rule fails loudly instead of being silently skipped. Everything under `tests/unit/` therefore runs anywhere, which is what makes the fast local loop possible.

`tests/integration/` needs the core only because the module under test imports `cat.log` and `cat.mad_hatter.decorators` at import time — **not** because a Cat must be running. Those tests never contact a live instance: the container is used as an interpreter, not as a server. Automated tests against a running instance do not exist yet; see *What is not automated* below.

One thing to know before adding files here: **the Cat imports every `.py` it finds in the plugin folder, recursively, including `tests/`**, and it does so under a package name where a bare `import checks` does not resolve. Left alone, that makes the core log `Unable to load plugin ict-site-rag-guards` on every activation — the plugin still works, because each file is imported inside its own `try`, but the message is alarming and hides real errors. Both test modules therefore put the plugin folder on `sys.path` before importing, which costs three lines and keeps a genuine breakage failing rather than skipping. It is also why `pytest.ini` and the two runner scripts are deliberately not Python files.

The `@hook` decorator turning functions into non-callable `CatHook` objects is covered under *Cheshire Cat AI hooks used* above.

### Environment setup

Two options, depending on which tests you want to run.

**Local interpreter — `tests/unit` only.** One-off, and nothing else is required because those tests use only the standard library:

```
python -m pip install pytest
```

**Container — the whole suite.** Nothing to install: `pytest` ships in the core image. The container must be running:

```
docker compose up -d
```

### Running the tests

Two equivalent runners live in the plugin root: `run-tests.ps1` for PowerShell and `run-tests.sh` for Linux and macOS. They wrap both environments, take the same three forms, and return pytest's own exit code. Run them from the plugin folder.

| What it runs | PowerShell | Linux / macOS |
| --- | --- | --- |
| `tests/unit` only, no container | `.\run-tests.ps1 -Unit` | `./run-tests.sh --unit` |
| the whole suite, in the container | `.\run-tests.ps1` | `./run-tests.sh` |
| the whole suite, one line per test | `.\run-tests.ps1 -Detailed` | `./run-tests.sh --detailed` |

Because the exit code is pytest's own, either script can be reused from a git hook or from CI. If a prerequisite is missing — no interpreter with `pytest`, container not running, `compose.yml` not where expected — they say which command fixes it instead of failing obscurely.

The `pre-commit` hook runs `tests/unit` too, and nothing else: a commit must not depend on Docker being up, or the hook would either block legitimate commits or skip in silence. `tests/integration` is for the runners, before pushing.

The shell version also handles two things the PowerShell one never meets: it falls back to the standalone `docker-compose` binary where Compose v2 is not a docker subcommand, and it picks the first interpreter that can actually import `pytest` rather than the first one on `PATH`, since a `python3` shim with no packages is common.

The git hooks deliberately keep referring to the PowerShell runner, because the development machine for this plugin is Windows.

Calling `pytest` directly works too. Locally:

```
python -m pytest tests/unit
```

In the container:

```
docker compose exec -w /app/cat/plugins/ict-site-rag-guards cheshire-cat-core python -m pytest
```

From Git Bash on Windows that same command fails with `Cwd must be an absolute path`, because the shell rewrites the `-w` path. Prefix it with `MSYS_NO_PATHCONV=1` — which is what `run-tests.sh` does, so it works under Git Bash as well as on Linux.

No `PYTHONPATH` is needed: `pytest.ini` declares `pythonpath = . /app`, where `.` makes the plugin modules importable and `/app` makes the core importable inside the container. A path that does not exist is ignored, so the same file works on a developer machine. Without that second entry `tests/integration/` is **skipped rather than failed**, which reads as a success — the reason it is configured in the file instead of being left to the caller.

### What is not automated

Verification against a real instance is currently manual: activate the plugin, send messages through `POST /message`, and read `docker compose logs -f cheshire-cat-core` to confirm which code path ran. A correct-looking answer does not prove it came from this plugin; the log lines do.

This tier matters because it catches what the other two cannot. The interaction with the `Rate Limiter` plugin is the case in point: its checks used to intercept messages before this plugin ever saw them, and nothing in the code of either plugin showed it — the first evidence came from a single live message and two consecutive log lines. The hook priority now settles who answers, and a unit test guards the priority, but the ordering itself is only ever confirmed on a running instance.

The same tier is where another plugin's side effects show up. Above its own `max_prompt_length`, Rate Limiter still records an infraction and suspends the user for 5, 15 or 60 minutes, silently blocking their next legitimate messages, even though the reply delivered is this plugin's. No test can see that either. See `DEV/ISSUES_TODO.md`.

## Roadmap (implementation & testing plan)

1. **Inventory** — confirm actual v1 version, available hooks, model, embedder, metadata structure, WordPress plugin behavior.
2. **Prototype** — implement `input_guard`, `rag_policy`, `evidence_gate`, `prompt_policy` with technical logging.
3. **Test corpus** — Italian/English questions: answerable, ambiguous, out-of-scope, PII, injection, conflicting sources.
4. **RAG tuning** — measure recall, precision, source quality; calibrate `k`, threshold, chunking.
5. **Adaptive output guard** — add local `output_guard`; introduce the judge only if tests show measurable benefit.
6. **Tokens & latency** — log input/output tokens and per-stage timing; compare baseline vs. proposed pipeline.
7. **Privacy & security** — validate payloads, logs, retention, external providers, secrets, and authenticated channels with the relevant stakeholders (incl. DPO).
8. **Release** — promote configuration through dev → pre-production → production with regression tests and sign-off.

## Not yet fixed (needs testing)

- LLM model and embedder
- Similarity threshold and final `k`
- Chunk size/overlap at ingestion
- Evidence-sufficiency rules and judge trigger conditions
- Retention, anonymization, and comment handling (to be agreed with the DPO)
- Latency, cost, quality, and max fallback-rate thresholds
- Cache strategy and invalidation conditions

## References

- Source document: *Workflow RAG Cheshire Cat AI — Chatbot ICT SNS* (internal)
- [Cheshire Cat AI flow hooks documentation](https://cheshire-cat-ai.github.io/docs/API_Documentation/mad_hatter/core_plugin/hooks/flow/)
- [Cheshire Cat AI core repository](https://github.com/cheshire-cat-ai/core)
- [Cheshire Cat Chatbot WordPress plugin](https://wordpress.org/plugins/cheshire-cat-chatbot)
