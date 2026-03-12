# ACH ODFI/RDFI Validation Utilities

Run the workflow:

```bash
python run_all.py config.sample.ini
```

## Retail ODFI indicator

If you set `aba_number` (one or more, comma/space-separated) in the `.ini`, the validator computes an overall summary based on:

```bash
grep '^5' *.ACH | cut -c41-50
```

If Type-5 positions 41-50 match any configured bank ABA (9 digits, or first 8 digits), the dataset is flagged as a **Retail ODFI indicator**. This is reported as **overall counts + percentage + files impacted**, plus a **per-ABA breakdown**, in the log output.
