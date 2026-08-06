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
- the fallback is a full replacement, not a local redaction
