# Output Guards

Current output-side guard behavior for `ict-site-rag-guards`.

This document describes only the output guards that exist today. The taxonomy
of `stage`, `category` and `verdict` is defined in
`DOC/GuardTaxonomy.md` and is not repeated here.

## Scope

The first output-guard iteration implements one check only:

- `stage='output'`
- `category='privacy'`
- `verdict='output_personal_data'`

It runs just before the generated answer is delivered to the user.

## Implemented check

### Personal data leakage

Purpose:

- stop generated replies that contain personal data

Detectors used:

- e-mail addresses
- phone numbers, validated with `phonenumberslite`
- codice fiscale, validated with its check character
- IBAN, validated with mod-97

The output guard deliberately reuses the same detector family already used on
input. The difference is not the detection logic, but the point in the flow,
the fallback text shown to the user, and the fact that output detectors are now
configured independently from input detectors.

## What happens when it blocks

When the check fires:

- the generated answer is not delivered as-is
- the plugin replaces it with a static fallback reply
- the line is logged as an output-side privacy block

The replacement happens before the answer is written to the AI side of the
conversation history as the final outgoing message.

## Available settings

The current output-side settings are:

- `Output privacy guard: block e-mail addresses`
- `Output privacy guard: block codice fiscale`
- `Output privacy guard: block IBAN`
- `Output privacy guard: block phone numbers`
- `Output privacy guard: region for phone numbers written without a prefix`
- `Output privacy guard: reply — outgoing personal data detected`

The output-side guard is active whenever at least one of those output detectors
is enabled.

The corresponding input-side privacy settings are independent:

- `Input privacy guard: block e-mail addresses`
- `Input privacy guard: block codice fiscale`
- `Input privacy guard: block IBAN`
- `Input privacy guard: block phone numbers`
- `Input privacy guard: region for phone numbers written without a prefix`
- `Input privacy guard: reply — personal data detected`

## Logging

Example block line:

```text
[ict-site-rag-guards] output blocked, stage='output', category='privacy', verdict='output_personal_data', detected=email; generated reply replaced before delivery
```

As on input:

- the refused/generated text itself is not logged
- the log records only the shape of the violation
- `stage`, `category` and `verdict` stay separate

## Known limits of v1

- only personal-data leakage is implemented on output
- no groundedness or citation-consistency check is active
- no output language check is active
- no register check on the answer is active
- the fallback is a full replacement, not a local redaction

## Verifications deliberately left outside v1

The three checks absent from this iteration are **decisions, not omissions**, and
each one is tracked somewhere so it does not have to be rediscovered. Do not
re-add them to a plan as missing work.

| Check | Intended taxonomy | Where it is tracked |
| --- | --- | --- |
| Answer language matches the question | `output` / `quality` / `output_language_mismatch` | An open issue in `DEV/AGENTS/ISSUES_TODO.md`, plus the manual checklist in `DOC/TestingCode.md`. Deliberately a **final verification**, not a guard |
| Groundedness and citation consistency | `output` / `quality` / `output_groundedness` | An open issue in `DEV/AGENTS/ISSUES_TODO.md`; architectural alternatives in `DEV/TODO/ResponseConsistencyChecksPlan.md` |
| Register of the answer | `output` / `tone` / `output_tone` | Planned for Fase 5 in `DEV/TODO/RagGuardsPlan.md`. Its category is `tone`, the same as the input offensive check — see `DOC/ToneGuards.md` |

Why the language check is a verification rather than a guard is worth knowing,
because it looks like an easy win: making the *model* answer in the language of
the question is a prompt instruction, already handled outside this plugin, and a
detector could only contradict it. Measured on the installed instance,
`langdetect` returns Afrikaans for `password` and German for `VPN`, both above
0.999 confidence. On a full answer the text is long enough to classify reliably,
which is why the door is left open — but the first step is confirming on the live
instance that the prompt instruction is honoured, not writing a check.

The groundedness one is the opposite case: it is the **highest-value control still
missing** from the pipeline, because it is the only one that would look at what
the model actually produced against the evidence it was given. It is deferred for
a concrete reason — it needs a citation format to compare against, and that
format is not defined yet.
