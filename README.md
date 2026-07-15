# Questrade RetailSessionData Enricher

Populate missing `RetailSessionData` fields on **TradeDelete**, **TradeEdit**,
and **TradeSubmit** events for Questrade Inc. Other event types already carry
these fields and are left unchanged.

## Missing fields

| Field | Source |
|-------|--------|
| `UTCTimestamp` | Enrichment CSV (preferred) or payload timestamp |
| `ImmutableUserID` | Enrichment CSV or payload `userId` |
| `IPAddress` | Enrichment CSV or payload `clientIp` |
| `SignOnId` | Enrichment CSV or payload `sessionId` |
| `UserAgentString` | Enrichment CSV or payload `userAgent` |

`Channel` is also written into `RetailSessionData` when available (CSV or event).

## Data path (Canada Host)

```text
tools-01.ps.ca2.fm-hosted.com
mounts/customer-data-prod/QuestradeIncON-Retail_UAT_5044/riskengine_structured_input/2026
```

## Enrichment CSV format

```csv
TransactionId,Channel,UTCTimestamp,ImmutableUserID,IPAddress,SignOnId,UserAgentString
3a65190d-3c01-46e2-05ef-403e11f59e0d,OLBRetail,1762135168,c654d961-d688-5d4c-a305-2ab67d785cee,135.315.218.31,3520006d-52be-4aa1-a70d-b95fd1e19209,Mozilla/5.0 ...
```

Rows are matched to events by `TransactionId`.

## Usage

```bash
cp config.ini.example config.ini
# edit paths in config.ini

python enrich_trade_session.py config.ini
```

Or without a config file:

```bash
python enrich_trade_session.py \
  --input /mounts/customer-data-prod/QuestradeIncON-Retail_UAT_5044/riskengine_structured_input/2026 \
  --csv /path/to/session_fields.csv \
  --output /path/to/enriched_output \
  --log-dir /path/to/logs
```

Dry-run (no writes):

```bash
python enrich_trade_session.py config.ini --dry-run
```

## How it works

1. Load the session CSV into a `TransactionId` lookup.
2. Walk JSON / JSONL files under the structured-input directory.
3. For `TradeDelete` / `TradeEdit` / `TradeSubmit` only:
   - Build `RetailSessionData` using CSV values first.
   - Fill any remaining blanks from payload paths used by reference events
     (`Login`, `FundTransfer`, etc.).
4. Leave all other event types untouched.
5. Write enriched files mirroring the input directory layout.

## Sample fixtures

```text
samples/
  enrichment/session_fields.csv     # CSV Questrade will share
  reference/reference_events.jsonl  # events that already have RetailSessionData
  input/2026/03/                    # trade events missing the hash
  output/                           # created by a sample run
```

## Tests

```bash
python -m unittest discover -s tests -v
```

## Project layout

```text
enrich_trade_session.py   # CLI / file processor
session_fields.py         # field mapping + RetailSessionData builder
config.ini.example
samples/
tests/
```
