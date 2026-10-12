---
description: Run the Phase 0 spike and turn its output into verified element names
---
Phase 0 (design doc 26) needs NSE access, so run this on an Indian network.

1. `uv run python scripts/phase0_spike.py --limit 10` (add `--symbols` for a bank and an NBFC).
2. Read `out/phase0/<latest>/summary.json` and `elements.csv`.
3. For each taxonomy seen, compare the element names with `analekh/xbrl/elements.py`. Replace
   `# verify` markers only for names actually present in the files; fill the empty BANKING and
   NBFC tables from the bank and NBFC filings.
4. Summarise validation failures per rule (V1-V10) and whether they come from real filing
   issues or from element-name assumptions.
5. Ask me to hand-check 10 values per file against the published results PDF before any
   value goes into the golden set. Do not commit the downloaded files.
