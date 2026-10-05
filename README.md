# Data Validation Framework (X9.37 + XML)

This project validates check-processing datasets in two modes:

- **X9.37 mode** (`validation_type = x937`)
- **XML mode** (`validation_type = xml`)

It provides:

- structural validation
- field-level validation
- transaction direction distribution
- amount and data-integrity checks
- return-record support
- investigation artifacts (TSV/JSON/log)

---

## 1) Repository structure

- `main.py`  
  Entry point. Reads config, sets logging, dispatches to X9 or XML validator.

- `x9_check_validation.py`  
  Core X9.37 parser and validator.

- `xml_validation.py`  
  XML validator with parallel reporting style.

- `xml_standard.py`  
  XML path/value converter utility.

- `log_manager.py`  
  Shared structured logging and summary formatting.

- `config.ini.example`  
  Sample runtime configuration.

---

## 2) Prerequisites

Python 3.9+ recommended.

Install dependencies:

```bash
pip install pandas chardet lxml
```

---

## 3) How to run

1. Copy and edit config:

```bash
cp config.ini.example config.ini
```

2. Run:

```bash
python3 main.py config.ini
```

---

## 4) Configuration

Main sections in `config.ini`:

### `[GENERAL]`

- `validation_type`: `x937` or `xml`
- `verbose_output`: `true/false`

### `[DATA]`

- `input_path`: directory containing files
- `sample_days`: `0` = all dates, `N` = first N detected business dates
- `tenant_name`: used in log filename

### `[X937]`

- `our_aba`: one or more ABA values (comma-separated)

### `[VALIDATION]`

- `bad_record_threshold`
- `allow_zero_amount`
- `allow_missing_amount`
- `onus_max_elements`
- `enable_duplicate_check`
- `enable_date_continuity`
- `enable_outlier_detection`
- `iqr_multiplier`
- `enable_sequence_check` (X9 only)
- `enable_hierarchical_report` (X9 only, performance option)

### `[LOGGING]`

Log filename is auto-generated:

`{tenant_name}_{YYYYMMDD_HHMM}.{X937|XML}.log`

---

## 5) X9 validation behavior

## 5.1 Structural checks

- Header must start with `01 -> 10 -> 20`
- `26` must follow `25`
- Each `25` must have at least one `26`
- Collection-aware required record types:
  - Presentment: `25/26/50/52`
  - Return: `31/32/50/52` (return optional unless return content exists)

## 5.2 Critical fields

Record-type checks include routing format/checksum, MICR presence, item amount presence, and return/addendum essentials.

## 5.3 Image linkage (item-level)

Per item (`25` or `31` context):

- **Required**: at least one `50`
- **Advisory**: `52` should be present when `50` exists

## 5.4 Direction distribution

X9 direction output is constrained to three categories:

- `DEPOSIT`
- `ON_US`
- `WITHDRAWAL`

Definitions are ABA-based using payor routing and BOFD routing.

## 5.5 Return handling

Return records (`31/32`) are validated and reported.
For return-only datasets, forward-only sections are skipped with explicit log messaging.

---

## 6) XML validation behavior

XML validator loads records through `xml_standard.Standard` and performs:

- bad record checks
- distribution checks
- amount checks
- duplicate checks
- return checks (when collection-type return records exist)

Use XML mode for `.xml` transformed inputs.

---

## 7) Output artifacts

Common:

- `*.log` validation report
- `forward_result_<date>.tsv`
- `return_result_<date>.tsv` (when return records exist, or placeholder in return-only logic)

X9-specific:

- `invalid_x937_structure_<date>.tsv`
- `missing_26_detail_<date>.tsv`
- `x937_hierarchical_report_<date>.json` (if enabled)
- `duplicate_checks_detail_<date>.tsv`
- `onus_duplicates_detail_<date>.tsv` (when ON_US duplicates are present)

---

## 8) Performance tuning

For large runs, set:

```ini
[VALIDATION]
enable_hierarchical_report = false
```

This skips expensive hierarchical JSON generation and reduces runtime.

Other practical tips:

- Use `sample_days` for quick diagnostics before full runs.
- Validate mode matches input file type (`x937` vs `xml`).
- Keep `input_path` focused to relevant batches only.

---

## 9) Troubleshooting

### "No ON_US/DEPOSIT/WITHDRAWAL shown"

Direction is calculated from valid forward RT25 records.  
If no valid forward records exist, distribution is skipped and a reason is logged.

### Header failures for all files

Likely input-mode mismatch (for example XML files in X9 mode), or non-X9 content.

### Unexpected duplicate volume

Check:

- `duplicate_checks_detail_*.tsv`
- `onus_duplicates_detail_*.tsv`

These include filename/account/check/sequence context for root-cause analysis.

---

## 10) Modules used

Standard library:

- `codecs`, `configparser`, `datetime`, `glob`, `json`, `logging`, `os`, `re`, `sys`, `traceback`, `typing`, `warnings`

Third-party:

- `pandas`
- `chardet`
- `lxml`

Local modules:

- `log_manager`
- `xml_standard`

---

## 11) Quick start examples

### Run X9 validation

```ini
[GENERAL]
validation_type = x937

[DATA]
input_path = /path/to/x9/files
sample_days = 0
tenant_name = DemoTenant

[X937]
our_aba = 083001314
```

```bash
python3 main.py config.ini
```

### Run XML validation

```ini
[GENERAL]
validation_type = xml
```

```bash
python3 main.py config.ini
```
