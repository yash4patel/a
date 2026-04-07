# ACH ODFI/RDFI Validation Utilities

Run the workflow:

```bash
python run_all.py config.sample.ini
```

## Agent-based summary (on-prem / optional)

After you run `run_all.py`, you’ll have a combined JSON report next to the log (`*.ACH.json`).
You can generate a detailed, customer-ready summary from that JSON with:

```bash
# Deterministic (no LLM calls)
python ai_runner.py path/to/report.ACH.json --dry-run

# LLM-assisted (Ollama). Base URL can be host or /api; tool normalizes to /api.
python ai_runner.py path/to/report.ACH.json --ollama-url http://localhost:11434 --model llama3

# Optional: include validator encoding-integrity sanitized samples
# (raw previews are removed; filenames/line numbers only included if you also set --allow-sensitive-evidence)
python ai_runner.py path/to/report.ACH.json --ollama-url http://localhost:11434 --model llama3 --include-sanitized-samples --max-samples 20
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
