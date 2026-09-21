# ACH ODFI/RDFI Validation Utilities

Run the workflow:

```bash
python run_all.py config.sample.ini
```

## Agent-based summary (deterministic / optional)

You can configure `run_all.py` to automatically generate a detailed, customer-ready summary (`*.ai_summary.md` + `*.ai_summary.json`) from the combined report JSON (`*.ACH.json`) in deterministic mode (no external model calls).

In `config.ini`, set:

- `ai_summary_enabled = True`
- `ai_summary_dry_run = True` (kept for backward compatibility; summary generation is deterministic)

You can still run the summarizer directly if desired:

```bash
# Deterministic summary (no external model calls)
python ai_runner.py path/to/report.ACH.json

# Optional: include validator encoding-integrity sanitized samples
# (raw previews are removed; filenames/line numbers only included if you also set --allow-sensitive-evidence)
python ai_runner.py path/to/report.ACH.json --include-sanitized-samples --max-samples 20
```

This produces:
- `report.ACH.ai_summary.md`
- `report.ACH.ai_summary.json`

## Retail ODFI indicator

If you set `aba_number` (one or more, comma/space-separated) in the `.ini`, the validator computes an overall summary based on:

```bash
grep '^5' *.ACH | cut -c41-50
```

If Type-5 positions 41-50 match any configured bank ABA (9 digits, or first 8 digits), the dataset is flagged as a **Retail ODFI indicator**. This is reported as **overall counts + percentage + files impacted**, plus a **per-ABA breakdown**, in the log output.
