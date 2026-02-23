# Cross-Channel Reference Validator

A Python-based validation framework to validate reference CSV files such as
Account, Party, ACH ODFI, Business, and Retail. It also performs cross-channel
matching against historical ACH, Check, and Wire data to report the percentage
of records that match the reference files.

---

## Features

- Supports multiple reference channels:
  - Account
  - Party
  - ACH ODFI
  - Business
  - Retail
- Schema-driven validation using JSON configuration
- Required and optional field validation
- Format validation (dates, money, flags, ASCII)
- Automatic normalization (T/F flags, money values, status)
- Single and composite primary key validation
- Progress logging for large files
- Cross-reference (Account <-> Party) and cross-channel matching (ACH/Check/Wire)
- Generates cleaned CSVs, error reports, and cross-channel summaries
- Centralized logging with per-run log files

---

## Project Structure

```
.
├── validator.py              # Main validator script
├── cross_reference.py        # Cross-channel checks (ACH/Check/Wire)
├── log_manager.py            # Logging utility
├── config.ini.example        # Example configuration
├── reference_schema2.json    # JSON schema definitions
├── reports/                  # Output directory (configurable)
│   ├── logs/                 # Log files
│   ├── *_validation_*.tsv    # Error reports
│   ├── *_cleaned_*.csv       # Cleaned output files
│   └── cross_channel_summary_*.tsv
└── README.md
```

---

## Configuration (config.ini)

```ini
[GENERAL]
tenant_name = MyTenant

[CSV FILE INPUT]
account = /path/to/Account.csv
party = /path/to/Party.csv
achodfi = /path/to/ACHODFI.csv
business = /path/to/Business.csv
retail = /path/to/Retail_ABC_20260131.csv

[CROSS-CHANNEL]
ach_dir = /path/to/ach/files
check_dir = /path/to/check/xml
wire_dir = /path/to/wire/logs
ach_glob = *ACH,*ach
check_glob = *.xml,*.XML
wire_glob = **/*.log,**/*.LOG

[OUTPUT]
output_dir = ./reports

[SCHEMA]
json_schema_file = ./reference_schema2.json

[OPTIONS]
cross_check_party = true
cross_check_ach = true
cross_check_check = true
cross_check_wire = true
strip_leading_zeros = true
```

Notes:
- `*_dir` values are the folders to search.
- `*_glob` values are the filename patterns (comma-separated) used within those
  folders (wire globs are recursive).

---

## Supported File Types and Rules

### Account
- Primary Key: `AccountNumber`
- At least one balance field required
- Validates dates, money fields, flags, and account status
- `AccountType` required (Business|Personal|Other)
- `AccountName` optional (< 100 chars)
- `DisplayFields` optional (`key=value` pairs separated by `#%#`, < 1000 chars)

### Party
- Primary Key: `PartyID`
- Validates customer type, dates, and contact details

### ACH ODFI
- Primary Key: `ACHCompanyID`
- Validates ODFI setup and settlement details

### Business
- Composite Primary Key: `(OnlineCompanyID, UserID)`
- Required columns: `PartyID`, `OnlineCompanyID`, `UserID`
- All values must be ASCII and < 100 characters

### Retail
- Primary Key: `UserID`
- Required columns: `PartyID`, `UserID`

---

## JSON Schema Configuration

Each file type is mapped using `file_pattern` and `header`.

Example:

```json
{
  "file_pattern": "Retail_.*_\\d{8}\\.csv",
  "header": "PartyID,UserID"
}
```

- Missing columns are reported as errors
- Extra columns are ignored (logged as warnings)

---

## Cross-Reference and Cross-Channel Matching

Phase 2 (Cross-Reference) checks Account ↔ Party consistency and writes:
`cross_party_reference_issues_<tenant>_<timestamp>.tsv`.

Phase 3 (Cross-Channel) checks accounts/parties against ACH, Check, and Wire
transaction files.

For each channel, the validator computes:
- Account match percentage (historical accounts found in Account reference)
- Party match percentage (historical accounts map to PartyIDs in Party reference)

Outputs include per-channel unmatched account/party lists and a summary TSV.

---

## Outputs

All outputs are written to `OUTPUT.output_dir`:

- `account_validation_<tenant>_<timestamp>.tsv`
- `account_cleaned_<tenant>_<timestamp>.csv`
- `party_validation_<tenant>_<timestamp>.tsv`
- `party_cleaned_<tenant>_<timestamp>.csv`
- `achodfi_validation_<tenant>_<timestamp>.tsv`
- `achodfi_cleaned_<tenant>_<timestamp>.csv`
- `business_validation_<tenant>_<timestamp>.tsv`
- `business_cleaned_<tenant>_<timestamp>.csv`
- `retail_validation_<tenant>_<timestamp>.tsv`
- `retail_cleaned_<tenant>_<timestamp>.csv`
- `cross_party_reference_issues_<tenant>_<timestamp>.tsv`
- `cross_reference_summary_<tenant>_<timestamp>.tsv`
- `ach_unmatched_accounts_<tenant>_<timestamp>.tsv`
- `ach_unmatched_parties_<tenant>_<timestamp>.tsv`
- `check_unmatched_accounts_<tenant>_<timestamp>.tsv`
- `check_unmatched_parties_<tenant>_<timestamp>.tsv`
- `wire_unmatched_accounts_<tenant>_<timestamp>.tsv`
- `wire_unmatched_parties_<tenant>_<timestamp>.tsv`
- `cross_channel_summary_<tenant>_<timestamp>.tsv`

Cross-channel unmatched reports include:
- rank
- count
- percent of channel records
- percent of unmatched records

Log files are written to:

```
<output_dir>/logs/validation_<tenant>_<timestamp>.log
```

---

## How to Run

```bash
cp config.ini.example config.ini
python validator.py config.ini
```

---

## Notes

- Account numbers are normalized by default by stripping leading zeros
  when the value is all digits. Disable with `strip_leading_zeros = false`.