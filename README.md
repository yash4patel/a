# ACH ODFI/RDFI Validation Utilities

Run the workflow:

```bash
python run_all.py config.sample.ini
```

## Agent-based summary (on-prem / optional)

You can configure `run_all.py` to automatically generate a detailed, customer-ready summary (`*.ai_summary.md` + `*.ai_summary.json`) from the combined report JSON (`*.ACH.json`) using on-prem Ollama (optional) or deterministic mode (no LLM).

In `config.ini`, set:

- `ai_summary_enabled = True`
- `ai_summary_dry_run = True` (deterministic) **or** `False` (use Ollama)
- `ollama_base_url = http://localhost:11434` and `ollama_model = <model>` if using Ollama

You can still run the summarizer directly if desired:

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

## Metadata-driven checks (SQL/JSON)

This repo supports an optional **metadata-driven** execution mode where:
- Validation sections can be enabled/disabled from metadata
- Thresholds/parameters can be overridden from metadata
- Individual `ach_mdv_validator` checks can be enabled/disabled from metadata

Metadata can be stored in SQL as JSON (MySQL) or provided as a local JSON file.

### Local JSON ruleset

In `config.ini`:
- `metadata_enabled = True`
- `metadata_source = file`
- `metadata_json_path = metadata.sample.ruleset.json`

### MySQL ruleset

Use the DDL in `metadata.mysql.ddl.sql` to create the table, then insert a ruleset row.
In `config.ini`:
- `metadata_enabled = True`
- `metadata_source = mysql`
- `metadata_mysql_host = ...`
- `metadata_mysql_user = ...`
- `metadata_mysql_password = ...`
- `metadata_mysql_database = ...`
- `metadata_mysql_table = validation_ruleset`
- `metadata_ruleset_name = default`

## MongoDB sink (workflow JSON)

If enabled, the combined workflow JSON report is inserted into MongoDB as a single document.
In `config.ini`:
- `mongo_enabled = True`
- `mongo_uri = mongodb://...`
- `mongo_database = ps_auto`
- `mongo_collection = validation_runs`

## Retail ODFI indicator

If you set `aba_number` (one or more, comma/space-separated) in the `.ini`, the validator computes an overall summary based on:

```bash
grep '^5' *.ACH | cut -c41-50
```

If Type-5 positions 41-50 match any configured bank ABA (9 digits, or first 8 digits), the dataset is flagged as a **Retail ODFI indicator**. This is reported as **overall counts + percentage + files impacted**, plus a **per-ABA breakdown**, in the log output.
