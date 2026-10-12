# Known discrepancy: neatlogs vs list-price cost for claude-sonnet-5-5

| Source | Rate per MTok (in/out) | Cost of the same call (131 in / 18 out) |
|---|---|---|
| Anthropic list price (cached 2026-10-06), **used by Culprit** | $2 / $10 | $0.000442 |
| neatlogs `costUsd` on the LLM span (not used) | $3 / $15 (implied) | $0.000663 |

- **Trace:** `ffdf497989747bf30856935f187e6013` (span `claude-sonnet-5-5`, type LLM), read back with `scripts/nl-read --json traces spans list ffdf497989747bf30856935f187e6013 --type LLM`.
- **Rule:** all cost numbers in Culprit (ledger, reports, `export-costs`, cfo.ai) use the list price.
