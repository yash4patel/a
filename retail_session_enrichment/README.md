# RetailSessionData enrichment (Questrade Inc.)

Populate the missing `RetailSessionData` fields on the *new* RiskEngine trade
events for customer **Questrade Inc.** (`QuestradeIncON-Retail`).

## Problem

In the `riskengine_structured_input` feed, the newer event types are missing
session fields that the established events already carry. Questrade expects the
`RetailSessionData` hash to be populated for these events too.

Missing fields:

- `UTCTimestamp`
- `ImmutableUserID`
- `IPAddress`
- `SignOnId`
- `UserAgentString`

Event types to fix (the "new events"):

- `TradeDelete`
- `TradeEdit`
- `TradeSubmit`

Other event types are already correct and are left untouched.

## Where the values come from

Exactly as described by the customer, the values have two sources:

1. **From the supplemental CSV** (keyed by `TransactionId`):

   ```csv
   TransactionId,Channel,UTCTimestamp,ImmutableUserID,IPAddress,SignOnId,UserAgentString
   ```

   The five missing fields are read from this file, matched on `TransactionId`.
   `UTCTimestamp` is coerced to an integer epoch; the rest stay strings. Quoted
   values (e.g. a `UserAgentString` containing commas) are parsed correctly.

2. **From the existing payload.** The tool does **not** hard-code which extra
   fields belong in `RetailSessionData`. Instead it learns the correct shape
   from the *other* (already-correct) events in the same dataset — "use other
   events as reference for how these missing fields should be populated" — and
   mirrors any additional keys (e.g. `Channel`, `TransactionId`) by pulling
   their values from the new event's own payload.

## Behaviour

- **Idempotent** — a field is only written when it is missing/empty, so the
  tool can be re-run safely.
- **Non-destructive** — existing values are never overwritten.
- **Format-preserving** — JSON Lines in → JSON Lines out; JSON array in → JSON
  array out (auto-detected).
- **Auditable** — prints a JSON summary of exactly what changed, including
  any events with no matching CSV row (`events_missing_csv_match`) and
  per-field unresolved counts.

## Usage

```bash
python enrich_retail_session_data.py <events.jsonl> \
    --csv session_lookup.csv \
    --output events.enriched.jsonl \
    --report report.json
```

Useful options:

- `--event-types TradeDelete,TradeEdit,TradeSubmit` — override the target set.
- `--session-field RetailSessionData` — override the hash name.
- `--dry-run` — compute and report without writing output.

### Example

```bash
python enrich_retail_session_data.py sample/events_before.jsonl \
    --csv sample/session_lookup.csv \
    --output sample/events_after.jsonl
```

`sample/events_before.jsonl` and `sample/events_after.jsonl` show a before/after
of the transformation, including:

- a fully-populated `TradeSubmit` (all five fields from CSV + `Channel` /
  `TransactionId` mirrored from the reference event),
- a `TradeEdit` with a pre-existing partial hash that is completed,
- a `TradeDelete` with an empty hash that is populated,
- a `TradeSubmit` with no CSV match (fields left unresolved and reported).

## Tests

```bash
python -m pytest
```

## Notes / assumptions

- Records are treated generically as JSON objects. Each event is expected to
  expose an event-type field (`EventType`/`eventType`/`event_type`/
  `MessageType`/`Type`) and a `TransactionId`.
- The customer data itself lives on the customer host under
  `mounts/customer-data-prod/QuestradeIncON-Retail_UAT_5044/riskengine_structured_input/<year>`
  and is **not** stored in this repository. Point the tool at those files when
  running against real data.
