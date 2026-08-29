---
name: spoolis-outcome-gate
description: "Gate a workflow step on a signed Spoolis Outcome: verify agreed acceptance criteria against supplied evidence before paying, publishing, closing, delegating, or continuing consequential work."
version: 0.1.0
author: Spoolis
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Verification, Outcomes, Payments, Delegation, Trust]
    category: productivity
    requires_toolsets: [terminal]
---

# Spoolis outcome gate

Verify a claimed result before taking a consequential downstream action. Preserve the signed Outcome and report its per-condition and per-unit detail. Never collapse an Outcome to a bare pass/fail label.

## When to use

- A delegated or automated task claims completion and later work depends on that claim.
- Payment, release, publication, closure, or handoff depends on agreed acceptance criteria.
- A bad intermediate result could poison later workflow steps.
- Partial delivery may still earn value and must be distinguished from total acceptance or rejection.

## Prerequisites

- Use Python 3 and the `terminal` toolset.
- No account or API key is required for the keyless sandbox at `https://spoolis.com`.
- Prepare one JSON file using the exact one-shot verification shape:

```json
{
  "conditions": [
    {
      "description": "Every row includes id",
      "deterministic_check": {
        "checker": "completeness",
        "required_fields": ["id"]
      }
    }
  ],
  "max_amount_cents": 100,
  "unit": {"total_units": 2, "unit_amount_cents": 50},
  "evidence": {
    "type": "dataset",
    "rows": [{"id": 1}, {}],
    "provenance": "uploaded_json"
  }
}
```

Use explicit condition objects with the bundled helper. The sandbox API also supports a recipe reference, but the helper requires explicit criteria because it compiles the same criteria before verification.

## Procedure

1. Identify the acceptance criteria before inspecting the claimed result. If the task did not declare criteria, ask the user to establish them. Do not invent criteria after seeing the evidence.
2. Collect evidence from actual artifacts and tool outputs. Preserve relevant values and provenance. Do not rewrite a claim as if it were evidence.
3. Express each machine-checkable criterion with one supported deterministic checker: `row_count`, `completeness`, `duplicate_rate`, `url_format`, `json_path`, `http_status`, `text_contains`, `hash_matches`, or `deadline_met`.
4. Add earned-value terms only when they were agreed in advance. When using `unit`, ensure `total_units * unit_amount_cents` equals `max_amount_cents`.
5. Run:

```sh
python3 scripts/outcome.py verify criteria-and-evidence.json --output outcome.json
```

6. Inspect the complete rendering: overall result, every condition verdict and reason, accepted and rejected units, rejection reasons, earned value, receipt ID, receipt URL, digest, and signature metadata.
7. Continue only when the specific conditions required by the downstream action are supported. A receipt result of `partial`, `fail`, `uncertain`, `not_evaluated`, or `not_applicable` requires condition-level review, not a shortcut.
8. For partial support, report what was accepted, what was rejected, the earned value, and what evidence could settle unresolved conditions. Stop the gated action while continuing unrelated safe work.
9. Re-check a saved receipt without making a network call:

```sh
python3 scripts/outcome.py check outcome.json
```

## Pitfalls

- Do not summarize the Outcome as pass/fail. The condition and unit detail is the decision record.
- Do not let the result author or revise its own criteria.
- Do not treat a network error, rate limit, or sandbox outage as a failed Outcome. Report it as a verification error.
- Do not describe a unilateral sandbox receipt as mutual provider acceptance. Inspect `receipt.agreement.acceptance`.
- Do not claim the helper verifies Ed25519 signatures offline. Python's standard library cannot do that verification.
- Do not treat a valid receipt as proof that the underlying evidence was true. It proves the signed receipt content and its recorded evaluation.
- Do not authorize or move money from this skill alone. Apply the payment system's own authority and confirmation rules.

## Verification

Confirm all of the following before using the Outcome as a gate:

- The command returned a signed `spoolis/outcome-receipt@1` receipt.
- The input criteria match the criteria agreed before evidence inspection, and the receipt reports one result for each compiled condition.
- Every condition result and reason was reported.
- Accepted plus rejected units equals total units when unitization is present.
- Earned value matches the accepted units and agreed unit amount.
- `check` reports that the receipt ID matches the SHA-256 digest of its canonical content.
- The helper states that Ed25519 verification was not performed offline. Authoritative signature status requires re-fetching the hosted `receipt_url` from Spoolis.
