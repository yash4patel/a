# Cross-Channel Reference Validator

This tool validates reference Account/Party files and verifies that
historical channel data (ACH, Check, Wire) matches those references.
It reports the percentage of records that match per channel.

## Usage

1. Copy the example config and edit paths:

```
cp config.ini.example config.ini
```

2. Run the validator:

```
python validator.py config.ini
```

## Outputs

All outputs are written to `OUTPUT.output_dir`:

- `account_validation_<tenant>_<timestamp>.tsv`
- `account_cleaned_<tenant>_<timestamp>.csv`
- `party_validation_<tenant>_<timestamp>.tsv`
- `party_cleaned_<tenant>_<timestamp>.csv`
- `cross_party_reference_issues_<tenant>_<timestamp>.tsv`
- `ach_unmatched_accounts_<tenant>_<timestamp>.tsv`
- `ach_unmatched_parties_<tenant>_<timestamp>.tsv`
- `check_unmatched_accounts_<tenant>_<timestamp>.tsv`
- `check_unmatched_parties_<tenant>_<timestamp>.tsv`
- `wire_unmatched_accounts_<tenant>_<timestamp>.tsv`
- `wire_unmatched_parties_<tenant>_<timestamp>.tsv`
- `cross_channel_summary_<tenant>_<timestamp>.tsv`

## Notes

- Account numbers are normalized by default by stripping leading zeros
  when the value is all digits. Disable with `strip_leading_zeros = false`.