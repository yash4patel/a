# ACH ODFI/RDFI Validation Utilities

Run the workflow:

```bash
python run_all.py config.sample.ini
```

## Retail ODFI indicator

If you set `aba_number` in the `.ini`, the validator computes an overall summary based on:

```bash
grep '^5' *.ACH | cut -c41-50
```

If Type-5 positions 41-50 match your bank ABA (9 digits, or first 8 digits), the dataset is flagged as a **Retail ODFI indicator**. This is reported as **counts + percentage + files impacted** in the log output.
