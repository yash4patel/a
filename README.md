# Cross-Channel Reference Validator

This tool verifies that reference Account/Party files match historical
channel data (ACH, Check, Wire) and reports the percentage of records
that match per channel.

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

- `cross_party_reference_issues.tsv`
- `ach_unmatched_accounts.tsv`
- `ach_unmatched_parties.tsv`
- `check_unmatched_accounts.tsv`
- `check_unmatched_parties.tsv`
- `wire_unmatched_accounts.tsv`
- `wire_unmatched_parties.tsv`
- `validation_summary.tsv`

## Notes

- Account numbers are normalized by default by stripping leading zeros
  when the value is all digits. Disable with `strip_leading_zeros = false`.