#!/usr/bin/env python3
"""Populate the RetailSessionData hash for new RiskEngine event types.

Background
----------
For customer *Questrade Inc.* (QuestradeIncON-Retail) the RiskEngine
``riskengine_structured_input`` feed is missing a number of session fields on
the newer trade event types. Older/established event types already carry a
fully populated ``RetailSessionData`` hash; the new events do not.

This tool fills, for the configured *new* event types, the missing fields:

    UTCTimestamp, ImmutableUserID, IPAddress, SignOnId, UserAgentString

using two sources, exactly as described by the customer:

1. Values that come from the supplemental CSV file (keyed by ``TransactionId``):
       TransactionId, Channel, UTCTimestamp, ImmutableUserID,
       IPAddress, SignOnId, UserAgentString
2. Values that must be *extracted from the existing payload*. Rather than
   hard-coding which fields those are, we learn the shape of a correct
   ``RetailSessionData`` hash from the *other* (already-correct) events in the
   same dataset and mirror it for the new events.

Design goals
------------
* **Idempotent** - a field is only populated when it is missing/empty, so the
  tool can be re-run safely.
* **Non-destructive** - existing values are never overwritten.
* **Format-preserving** - JSON Lines in => JSON Lines out; JSON array in =>
  JSON array out.
* **Auditable** - a summary of exactly what was changed is emitted.

The record format is intentionally treated generically (a JSON object per
event) so the same tool works regardless of the exact RiskEngine schema
version, as long as each event exposes an event-type field and a
``TransactionId``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# --- Defaults ---------------------------------------------------------------

# Fields that are supplied by the supplemental CSV, keyed by TransactionId.
CSV_SESSION_FIELDS: Tuple[str, ...] = (
    "UTCTimestamp",
    "ImmutableUserID",
    "IPAddress",
    "SignOnId",
    "UserAgentString",
)

# The new event types that are missing the session fields.
DEFAULT_TARGET_EVENT_TYPES: Tuple[str, ...] = (
    "TradeDelete",
    "TradeEdit",
    "TradeSubmit",
)

# Name of the hash that holds the session information inside each event.
DEFAULT_SESSION_FIELD = "RetailSessionData"

# Candidate keys that identify the event type within an event object.
EVENT_TYPE_KEYS: Tuple[str, ...] = (
    "EventType",
    "eventType",
    "event_type",
    "MessageType",
    "Type",
)

# Candidate keys that identify the transaction id within an event object.
TXN_ID_KEYS: Tuple[str, ...] = (
    "TransactionId",
    "transactionId",
    "transaction_id",
    "TransactionID",
)

# Fields the CSV carries that are not session values themselves.
CSV_KEY_FIELD = "TransactionId"


# --- Helpers ----------------------------------------------------------------


def _is_empty(value: Any) -> bool:
    """A field counts as "missing" when it is absent, None or an empty string."""
    return value is None or (isinstance(value, str) and value.strip() == "")


def _coerce_value(field_name: str, raw: str) -> Any:
    """Coerce CSV string values to their natural type.

    UTCTimestamp is an epoch integer in the feed; everything else stays a
    string. Malformed timestamps are kept as the original string so nothing is
    silently dropped.
    """
    raw = raw.strip()
    if field_name == "UTCTimestamp":
        try:
            return int(raw)
        except (TypeError, ValueError):
            return raw
    return raw


def _first_present(obj: Dict[str, Any], candidates: Iterable[str]) -> Optional[str]:
    """Return the value of the first candidate key present in ``obj``."""
    for key in candidates:
        if key in obj and not _is_empty(obj[key]):
            return obj[key]
    return None


def _find_in_payload(event: Dict[str, Any], key: str) -> Any:
    """Locate ``key`` somewhere in the event payload.

    Preference order:
      1. Top-level exact match.
      2. Top-level case-insensitive match.
      3. First match found anywhere in the nested structure.
    """
    if key in event and not _is_empty(event[key]):
        return event[key]

    lowered = key.lower()
    for k, v in event.items():
        if k.lower() == lowered and not _is_empty(v):
            return v

    # Recursive fallback.
    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            for k, v in node.items():
                if k.lower() == lowered and not _is_empty(v):
                    return v
            for v in node.values():
                found = _walk(v)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = _walk(item)
                if found is not None:
                    return found
        return None

    return _walk(event)


# --- I/O --------------------------------------------------------------------


@dataclass
class ParsedInput:
    events: List[Dict[str, Any]]
    is_json_array: bool


def load_events(path: Path) -> ParsedInput:
    """Load events from JSON Lines or a JSON array, auto-detecting the format."""
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("["):
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError(f"{path}: top-level JSON must be an array of events")
        return ParsedInput([e for e in data if isinstance(e, dict)], is_json_array=True)

    events: List[Dict[str, Any]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{lineno}: invalid JSON line: {exc}") from exc
        if isinstance(obj, dict):
            events.append(obj)
    return ParsedInput(events, is_json_array=False)


def write_events(path: Path, events: List[Dict[str, Any]], is_json_array: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if is_json_array:
        path.write_text(json.dumps(events, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        lines = [json.dumps(e, ensure_ascii=False) for e in events]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_session_csv(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load the supplemental CSV into a ``{TransactionId: {field: value}}`` map.

    Uses the stdlib csv reader so quoted fields (e.g. UserAgentString values
    that contain commas) are handled correctly.
    """
    import csv

    lookup: Dict[str, Dict[str, Any]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            return lookup
        # Normalise header whitespace (the sample header has stray spaces).
        header_map = {name: name.strip() for name in reader.fieldnames}
        for row in reader:
            clean = {header_map.get(k, k): (v if v is not None else "") for k, v in row.items()}
            txn_id = (clean.get(CSV_KEY_FIELD) or "").strip()
            if not txn_id:
                continue
            record: Dict[str, Any] = {}
            for fname in CSV_SESSION_FIELDS:
                if fname in clean and not _is_empty(clean[fname]):
                    record[fname] = _coerce_value(fname, str(clean[fname]))
            lookup[txn_id] = record
    return lookup


# --- Enrichment core --------------------------------------------------------


def get_event_type(event: Dict[str, Any]) -> Optional[str]:
    return _first_present(event, EVENT_TYPE_KEYS)


def get_transaction_id(event: Dict[str, Any]) -> Optional[str]:
    value = _first_present(event, TXN_ID_KEYS)
    return str(value) if value is not None else None


def derive_reference_template(
    events: List[Dict[str, Any]],
    target_types: Iterable[str],
    session_field: str,
) -> List[str]:
    """Learn the RetailSessionData key set from the *other* (correct) events.

    We look at every event that is NOT a target type and that already has a
    populated session hash, and return the ordered union of keys observed.
    These represent "how other events populate the missing fields".
    """
    targets = set(target_types)
    ordered_keys: List[str] = []
    seen = set()
    for event in events:
        etype = get_event_type(event)
        if etype in targets:
            continue
        session = event.get(session_field)
        if not isinstance(session, dict):
            continue
        for key in session:
            if key not in seen and not _is_empty(session[key]):
                seen.add(key)
                ordered_keys.append(key)
    return ordered_keys


@dataclass
class EnrichmentStats:
    total_events: int = 0
    target_events: int = 0
    events_enriched: int = 0
    events_already_complete: int = 0
    events_missing_csv_match: int = 0
    fields_filled_from_csv: int = 0
    fields_filled_from_payload: int = 0
    unresolved_fields: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_events": self.total_events,
            "target_events": self.target_events,
            "events_enriched": self.events_enriched,
            "events_already_complete": self.events_already_complete,
            "events_missing_csv_match": self.events_missing_csv_match,
            "fields_filled_from_csv": self.fields_filled_from_csv,
            "fields_filled_from_payload": self.fields_filled_from_payload,
            "unresolved_fields": self.unresolved_fields,
        }


def enrich_event(
    event: Dict[str, Any],
    csv_lookup: Dict[str, Dict[str, Any]],
    reference_keys: List[str],
    session_field: str,
    stats: EnrichmentStats,
) -> bool:
    """Populate the session hash for a single target event in-place.

    Returns True if any field was added.
    """
    session = event.get(session_field)
    if not isinstance(session, dict):
        session = {}

    txn_id = get_transaction_id(event)
    csv_record = csv_lookup.get(txn_id, {}) if txn_id else {}
    if txn_id and not csv_record:
        stats.events_missing_csv_match += 1

    changed = False

    # 1) Fields supplied by the CSV, keyed by TransactionId.
    for fname in CSV_SESSION_FIELDS:
        if not _is_empty(session.get(fname)):
            continue
        if fname in csv_record:
            session[fname] = csv_record[fname]
            stats.fields_filled_from_csv += 1
            changed = True
        else:
            stats.unresolved_fields[fname] = stats.unresolved_fields.get(fname, 0) + 1

    # 2) Payload-derived fields: mirror the shape of correct events. Any key
    #    that other events carry in RetailSessionData but that is not a CSV
    #    field is looked up in this event's own payload.
    for key in reference_keys:
        if key in CSV_SESSION_FIELDS:
            continue
        if not _is_empty(session.get(key)):
            continue
        value = _find_in_payload(event, key)
        if not _is_empty(value):
            session[key] = value
            stats.fields_filled_from_payload += 1
            changed = True

    if changed or session_field not in event:
        event[session_field] = session
    return changed


def enrich_events(
    events: List[Dict[str, Any]],
    csv_lookup: Dict[str, Dict[str, Any]],
    target_types: Iterable[str],
    session_field: str = DEFAULT_SESSION_FIELD,
) -> EnrichmentStats:
    targets = set(target_types)
    reference_keys = derive_reference_template(events, targets, session_field)
    stats = EnrichmentStats()

    for event in events:
        stats.total_events += 1
        etype = get_event_type(event)
        if etype not in targets:
            continue
        stats.target_events += 1

        session = event.get(session_field)
        already_complete = (
            isinstance(session, dict)
            and all(not _is_empty(session.get(f)) for f in CSV_SESSION_FIELDS)
        )

        changed = enrich_event(event, csv_lookup, reference_keys, session_field, stats)
        if changed:
            stats.events_enriched += 1
        elif already_complete:
            stats.events_already_complete += 1

    return stats


# --- CLI --------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Populate missing RetailSessionData fields for new RiskEngine "
        "trade events (Questrade).",
    )
    parser.add_argument("input", type=Path, help="Input events file (JSONL or JSON array).")
    parser.add_argument(
        "--csv",
        type=Path,
        required=True,
        help="Supplemental CSV keyed by TransactionId.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file. Defaults to <input>.enriched with the same format.",
    )
    parser.add_argument(
        "--event-types",
        default=",".join(DEFAULT_TARGET_EVENT_TYPES),
        help="Comma-separated event types to enrich "
        f"(default: {','.join(DEFAULT_TARGET_EVENT_TYPES)}).",
    )
    parser.add_argument(
        "--session-field",
        default=DEFAULT_SESSION_FIELD,
        help=f"Name of the session hash (default: {DEFAULT_SESSION_FIELD}).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Optional path to write a JSON enrichment report.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and report changes without writing the output file.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    target_types = [t.strip() for t in args.event_types.split(",") if t.strip()]

    parsed = load_events(args.input)
    csv_lookup = load_session_csv(args.csv)
    stats = enrich_events(parsed.events, csv_lookup, target_types, args.session_field)

    output_path = args.output or args.input.with_suffix(args.input.suffix + ".enriched")

    if not args.dry_run:
        write_events(output_path, parsed.events, parsed.is_json_array)

    report = {
        "input": str(args.input),
        "output": None if args.dry_run else str(output_path),
        "csv": str(args.csv),
        "target_event_types": target_types,
        "session_field": args.session_field,
        "csv_transactions_loaded": len(csv_lookup),
        "stats": stats.to_dict(),
    }
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
