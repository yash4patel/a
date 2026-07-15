# Questrade RetailSessionData Backfill

Backfills missing `RetailSessionData` fields for customer **Questrade Inc**
(`QuestradeIncON-Retail_UAT_5044`) in the RiskEngine structured input
(data shared 20 Mar 2026 – 7 Jul 2026). Only new Trade events are affected:

- `TradeDelete`
- `TradeEdit`
- `TradeSubmit`

Missing fields populated inside the `RetailSessionData` hash:

- `UTCTimestamp`
- `ImmutableUserID`
- `IPAddress`
- `SignOnId`
- `UserAgentString`

## How values are resolved

1. **Customer CSV** (preferred), joined on `TransactionId`:

   ```
   TransactionId,Channel,UTCTimestamp,ImmutableUserID,IPAddress,SignOnId,UserAgentString
   ```

2. **Existing payload extraction** — when a transaction is not in the CSV,
   values are pulled from the event's own fields (timestamp / user id / ip /
   session / user-agent variants), mirroring how healthy events carry them.

Before fixing anything, the tool learns the exact `RetailSessionData` key
casing and location from healthy reference events (all other event types) so
the backfilled events match the existing data shape.

## Usage

```bash
cp config.ini.example config.ini   # then edit paths
python3 backfill_missing_fields.py config.ini
```

On the Canada host (`tools-01.ps.ca2.fm-hosted.com`) point `input_dir` at:

```
mounts/customer-data-prod/QuestradeIncON-Retail_UAT_5044/riskengine_structured_input/2026
```

### Modes (`[OPTIONS] mode`)

| Mode | Behaviour |
|---|---|
| `inspect` | Report only: which Trade events are missing which fields. |
| `dry-run` | Full run; writes a CSV report of every change that would be made. No file writes. |
| `apply` | Writes fixed files (to `<output_dir>/fixed/` by default, or in place with `.bak` backups when `in_place = true`). |

Recommended order: `inspect` → `dry-run` (review the change report) → `apply`.

### Outputs

- `logs/validator_<tenant>_<ts>.log` — run log with a summary of counts.
- `backfill_changes_<mode>_<ts>.csv` — every field fill: file, line,
  transaction id, event type, field, value, and source (`csv` or `payload`).
- `backfill_txn_not_in_csv_<ts>.csv` — TransactionIds of affected events not
  found in the customer CSV (share back with the customer if fields remain
  unresolved).

No third-party dependencies; Python 3.8+ standard library only.
