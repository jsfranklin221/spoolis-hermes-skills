# Spoolis skills for Hermes agents

Skills that let a [Hermes](https://github.com/NousResearch/hermes-agent) agent
gate consequential actions on a signed Spoolis Outcome: verify that delivered
work satisfied explicit acceptance criteria before paying, publishing,
closing, or continuing.

## Skills

- `skills/spoolis-outcome-gate`: verify a claimed result against
  agreed acceptance criteria through the keyless Spoolis sandbox and act on
  the signed Outcome. Reports per-condition verdicts, accepted and rejected
  units, and earned value. Never collapses an Outcome to pass/fail.

## Install

```sh
hermes skills install jsfranklin221/spoolis-hermes-skills
```

No account or API key is needed; the skill uses the keyless Spoolis sandbox
at https://spoolis.com. See each skill's SKILL.md for usage, pitfalls, and
verification steps.

## What Spoolis is

Spoolis is for transactions where payment depends on whether the agreed
outcome actually happened. It turns acceptance criteria into deterministic
checks, verifies delivered evidence, and issues a signed Outcome Receipt
recording what passed, what failed, and what was earned. Docs:
https://spoolis.com/docs

## License

MIT.
