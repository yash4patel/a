# ACH Validation & Analysis Framework

A complete Python-based framework for validating ACH files, analyzing ABA routing entropy, and evaluating batch date completeness. Production-ready, configurable via `config.ini`, designed for banking, fintech, and ACH operations teams.

---

## Overview

This framework performs **three major validations** on ACH data:

### 1. ACH Structural (RDV) Validation

- Validates record ordering (1, 5, 6, 7, 8, 9)
- Verifies line lengths (each record must be 94 chars)
- Detects invalid SEC codes
- Detects incorrect addendum counts (IAT, POS)
- **Retail ODFI check**: Type-5 positions 41-50 must NOT match bank ABA (set `aba_number` in config)
- Flags malformed or corrupt ACH files
- Skips binary/encrypted files automatically

### 2. ABA Entropy Analyzer

Uses distribution and entropy of ODFI/RDFI routing numbers to classify the dataset:

| Type     | Meaning                                      |
| -------- | -------------------------------------------- |
| **ODFI** | Originating Depository Financial Institution |
| **RDFI** | Receiving Depository Financial Institution  |

### 3. Batch Date Completeness Analyzer

- Missing days: detects days with zero or unusually low batches
- Too many batches: flags abnormally large-volume days
- Weekend filtering: removes Saturdays/Sundays
- US federal holidays: excluded via `USFederalHolidayCalendar`

---

## Project Structure

```
ach-payment-processing/
├── run_all.py
├── config.ini
├── requirements.txt
├── config.py
├── logger_utils.py
├── folder_tools.py
├── misc_functions.py
├── ach_mdv_validator.py
├── aba_entropy.py
├── batch_data_check.py
└── log/
```

---

## Configuration (`config.ini`)

| Key                   | Description                          |
| --------------------- | ------------------------------------ |
| `tenant_name`         | Used for log naming                  |
| `sid`                 | System/tenant ID                     |
| `data_path`           | Folder containing ACH files          |
| `log_path`            | Output log directory                 |
| `max_error_percent`   | Allowed % of bad files (default: 2) |
| `sec_codes`           | Allowed SEC codes                    |
| `extension`           | File extension filter (e.g., ACH)   |
| `is_folded`           | Must be True (requires folded data)  |
| `aba_number`          | Bank ABA for Retail ODFI check (optional) |

---

## Running the Tool

```bash
pip install -r requirements.txt
python run_all.py config.ini
```

**Execution flow:** ACH RDV Validation → ABA Entropy Classification → Batch Date Completeness Check

---

## Logs

Logs are written to:

```
<log_path>/<tenant>_<sid>_<timestamp>.ACH.log
```

---

## Troubleshooting

| Issue                        | Possible Fix                          |
| ---------------------------- | ------------------------------------- |
| `pd not defined`             | Ensure `pandas` is installed          |
| Wrong dates detected         | Check filename structure or date parser |
| No logs generated            | Check `log_path` permissions          |
| "Please Provide Folded Data!" | Set `is_folded = True` in config.ini  |
