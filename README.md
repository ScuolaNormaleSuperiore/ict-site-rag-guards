# ict-site-rag-guard

A single, modular Cheshire Cat AI plugin that adds input/output guardrails, RAG evidence gating, and token-budget controls to the Scuola Normale Superiore ICT chatbot, keeping the ordinary flow to one LLM call and escalating to an LLM judge only when risk or uncertainty justifies it.

## Status

Technical proposal — to be configured, measured, and tested against a real Cheshire Cat AI v1 installation. Hook names, thresholds, and budgets below are starting points, not approved requirements.

## Scope

- Informational, first-level assistant answering questions about SNS ICT services, based exclusively on official public sources.
- Anonymous access to the full public knowledge base; authentication is only used for authorized personalization.
- Italian and English supported from the first version.
- Out of scope for this version: ticketing, email, operational escalation, MCP, and system-level operations.
- "Correctness" is not automatically certifiable; the realistic control is groundedness of the answer in the retrieved sources.

## Why one plugin

The controls are not independent — they act in sequence on the same Working Memory (input guard → RAG query → evidence gate → prompt → output guard). A single plugin avoids hook-ordering conflicts between separate plugins, centralizes configuration, and lets the whole pipeline be tested as one unit. Internally, the plugin stays modular (see below).

## Architecture

The WordPress plugin remains the presentation channel. Cheshire Cat AI handles session, working memory, vector search, and the LLM call. `ict-site-rag-guard` hooks into the critical points and applies checks, thresholds, and fallback responses.

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

## Cheshire Cat AI hooks used

| Hook | Used by |
| --- | --- |
| `before_cat_reads_message` / `fast_reply` | `input_guard` |
| `cat_recall_query` | `rag_policy` |
| `before_cat_recalls_declarative_memories` | `rag_policy` |
| `after_cat_recalls_memories` / `agent_fast_reply` | `evidence_gate` |
| `before_agent_starts` (prompt hooks) | `prompt_policy` |
| `before_cat_sends_message` | `output_guard`, `session_policy` |
| `before_cat_stores_episodic_memory` | `session_policy` |
| `agent_allowed_tools = []` | `rag_policy` (tools disabled in v1) |

Hook names and signatures must be verified against the actual installed Cheshire Cat AI v1 instance before development; public docs may reflect a later core revision.

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