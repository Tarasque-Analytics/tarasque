# Relative Quadrant IC Test

Does per-ticker-relative threshold classification (β median of own
history) beat universal absolute (β=1.0) cutoffs?

Sign expectations: positive for `vol`, negative for `ret` and `dd`.

## Subset: `common`

| horizon | metric | n | abs | rel_full | rel_exp | best |
|---|---|---|---|---|---|---|
| 21 | dd | 1472 | -0.082 | -0.021 | -0.028 | abs |
| 21 | ret | 1472 | +0.036 | -0.023 | -0.025 | rel_exp |
| 21 | vol | 1472 | +0.228 | +0.015 | +0.017 | abs |
| 63 | dd | 1472 | -0.038 | +0.068 | +0.045 | abs |
| 63 | ret | 1472 | +0.124 | +0.065 | +0.056 | rel_exp |
| 63 | vol | 1472 | +0.231 | -0.083 | -0.079 | abs |
| 126 | dd | 1472 | -0.040 | +0.083 | +0.074 | abs |
| 126 | ret | 1472 | +0.126 | +0.079 | +0.076 | rel_exp |
| 126 | vol | 1472 | +0.235 | -0.091 | -0.095 | abs |

## Subset: `own`

| horizon | metric | n | abs | rel_full | rel_exp | best |
|---|---|---|---|---|---|---|
| 21 | dd | 2208 | -0.054 | -0.006 | -0.028 | abs |
| 21 | ret | 2208 | +0.058 | -0.015 | -0.025 | rel_exp |
| 21 | vol | 2208 | +0.268 | -0.025 | +0.017 | abs |
| 63 | dd | 2208 | -0.027 | +0.059 | +0.045 | abs |
| 63 | ret | 2208 | +0.125 | +0.027 | +0.056 | rel_full |
| 63 | vol | 2208 | +0.279 | -0.091 | -0.079 | abs |
| 126 | dd | 2208 | -0.026 | +0.059 | +0.074 | abs |
| 126 | ret | 2208 | +0.147 | +0.046 | +0.076 | rel_full |
| 126 | vol | 2208 | +0.296 | -0.084 | -0.095 | abs |

## How to read

- `abs`: universal β=1.0 cutoffs (existing classifier)
- `rel_full`: per-ticker median over the FULL trail (clean test of the idea, mild lookahead)
- `rel_exp`: per-ticker expanding-window median (≥8 prior snapshots; deployable)

**Verdict logic:**
- If `rel_full` AND `rel_exp` both beat `abs` on vol IC → ordinal framing is empirically additive.
- If only `rel_full` beats `abs` → forward leak is doing the work; not deployable as-is.
- If neither beats `abs` → ticker-relative framing doesn't help for THIS classifier.

Use the `common` subset for apples-to-apples comparison (same observations across schemes).