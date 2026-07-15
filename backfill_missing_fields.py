#!/usr/bin/env python3
"""
Questrade Inc (QuestradeIncON-Retail_UAT_5044) - RiskEngine structured input backfill.

Backfills missing RetailSessionData fields on new Trade events:

    TradeDelete, TradeEdit, TradeSubmit

Missing fields populated:

    UTCTimestamp, ImmutableUserID, IPAddress, SignOnId, UserAgentString

Values come from two sources, in order of preference:

  1. The customer-supplied CSV, keyed by TransactionId:
         TransactionId,Channel,UTCTimestamp,ImmutableUserID,IPAddress,SignOnId,UserAgentString
  2. Extraction from the existing event payload (e.g. the event's own
     timestamp / user id / ip fields), mirroring how healthy reference
     events (other event types) carry the same data.

The tool first learns from reference events (event types other than the
affected Trade events) where the RetailSessionData block lives and what the
exact field key casing is, then applies the same shape to the broken events.

Modes (set in config.ini, [OPTIONS] mode):

    inspect  - only analyse files: report where RetailSessionData sits on
               reference events and which fields are missing on Trade events.
    dry-run  - full run, report every change that WOULD be made. No writes.
    apply    - write updated files. Originals are kept as <name>.bak unless
               backups are disabled.

Usage:
    python backfill_missing_fields.py <config.ini>
"""

import configparser
import csv
import glob
import gzip
import io
import json
import logging
import os
import sys
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from log_manager import LogManager

# Fields that must be present inside RetailSessionData, in canonical casing
# (the casing actually written is learned from reference events when possible).
TARGET_FIELDS = [
    "UTCTimestamp",
    "ImmutableUserID",
    "IPAddress",
    "SignOnId",
    "UserAgentString",
]

# Event types that need the backfill.
DEFAULT_AFFECTED_EVENT_TYPES = ["TradeDelete", "TradeEdit", "TradeSubmit"]

# Keys (lowercased, non-alphanumeric stripped) that may identify the event type.
EVENT_TYPE_KEYS = {"eventtype", "event", "type", "messagetype", "eventname"}

# Keys that may identify the transaction id used to join against the CSV.
TRANSACTION_ID_KEYS = {"transactionid", "transactionuuid", "eventid", "id"}

# Fallback payload keys per target field, used when the CSV has no row for
# the transaction and the value must be extracted from the existing payload.
DEFAULT_PAYLOAD_FALLBACK_KEYS = {
    "UTCTimestamp": ["utctimestamp", "timestamp", "eventtimestamp", "eventtime", "time"],
    "ImmutableUserID": ["immutableuserid", "immutableuser", "userid", "customerid", "partyid"],
    "IPAddress": ["ipaddress", "clientipaddress", "clientip", "sourceip", "remoteip", "ip"],
    "SignOnId": ["signonid", "sessionid", "signonsessionid", "logonid", "sessionuuid"],
    "UserAgentString": ["useragentstring", "useragent", "browseragent", "httpuseragent"],
}

RETAIL_SESSION_KEY_NORM = "retailsessiondata"


def norm_key(key: str) -> str:
    """Normalise a dict key for tolerant matching: lowercase, alnum only."""
    return "".join(ch for ch in str(key).lower() if ch.isalnum())


def is_missing(value: Any) -> bool:
    """A field counts as missing when absent, None, or an empty/placeholder string."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip().lower() in ("", "null", "none", "n/a"):
        return True
    return False


class Config:
    """Configuration manager, same INI conventions as the other validators."""

    def __init__(self, config_path: str):
        cfg = configparser.ConfigParser()
        if not cfg.read(config_path):
            raise FileNotFoundError(f"Config file not found or empty: {config_path}")
        self.cfg = cfg

        self.input_dir = self._get("INPUT", "input_dir", required=True)
        self.input_globs = self._get_list("INPUT", "input_glob", "**/*")
        self.csv_file = self._get("INPUT", "csv_file", "")

        self.output_dir = self._get("OUTPUT", "output_dir", required=True)

        self.tenant_name = self._get("GENERAL", "tenant_name", "QuestradeIncON-Retail_UAT_5044")

        self.mode = self._get("OPTIONS", "mode", "dry-run").lower()
        if self.mode not in ("inspect", "dry-run", "apply"):
            raise ValueError(f"Invalid mode '{self.mode}' (expected inspect, dry-run or apply)")

        self.affected_event_types = self._get_list(
            "OPTIONS", "affected_event_types", ",".join(DEFAULT_AFFECTED_EVENT_TYPES)
        )
        self.in_place = self._get_bool("OPTIONS", "in_place", False)
        self.keep_backups = self._get_bool("OPTIONS", "keep_backups", True)
        self.allow_payload_fallback = self._get_bool("OPTIONS", "allow_payload_fallback", True)

        # Optional date window (inclusive) applied to the event UTC timestamp.
        self.date_from = self._get_epoch("OPTIONS", "date_from")
        self.date_to = self._get_epoch("OPTIONS", "date_to")

    def _get(self, section: str, key: str, default: str = "", required: bool = False) -> str:
        value = self.cfg.get(section, key, fallback=default).strip()
        if required and not value:
            raise ValueError(f"Missing required config value [{section}] {key}")
        return value

    def _get_list(self, section: str, key: str, default: str) -> List[str]:
        raw = self._get(section, key, default)
        return [v.strip() for v in raw.split(",") if v.strip()]

    def _get_bool(self, section: str, key: str, default: bool) -> bool:
        raw = self._get(section, key, str(default))
        return raw.lower() in ("1", "true", "yes", "y", "on")

    def _get_epoch(self, section: str, key: str) -> Optional[int]:
        raw = self._get(section, key, "")
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
                return int(dt.timestamp())
            except ValueError:
                continue
        raise ValueError(f"Cannot parse [{section}] {key} = '{raw}' as epoch or YYYY-MM-DD")


class CsvLookup:
    """TransactionId -> field values from the customer-supplied CSV."""

    def __init__(self, csv_path: str, logger: logging.Logger):
        self.logger = logger
        self.rows: Dict[str, Dict[str, str]] = {}
        self.duplicates = 0
        if csv_path:
            self._load(csv_path)

    def _load(self, csv_path: str) -> None:
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                raise ValueError(f"CSV has no header row: {csv_path}")
            # Header names may contain stray spaces (as in the sample the
            # customer shared); map normalised header -> canonical field name.
            header_map: Dict[str, str] = {}
            for raw_header in reader.fieldnames:
                normalised = norm_key(raw_header)
                for canonical in ["TransactionId", "Channel"] + TARGET_FIELDS:
                    if normalised == norm_key(canonical):
                        header_map[raw_header] = canonical
                        break
            missing_headers = {"TransactionId"} - set(header_map.values())
            if missing_headers:
                raise ValueError(f"CSV is missing required column(s): {missing_headers}")

            for raw_row in reader:
                row = {
                    header_map[k]: (v or "").strip()
                    for k, v in raw_row.items()
                    if k in header_map
                }
                txn_id = row.get("TransactionId", "")
                if not txn_id:
                    continue
                if txn_id in self.rows:
                    self.duplicates += 1
                self.rows[txn_id.lower()] = row

        self.logger.info(
            "Loaded %d CSV rows from %s (%d duplicate TransactionIds, last one wins)",
            len(self.rows),
            csv_path,
            self.duplicates,
        )

    def get(self, transaction_id: str) -> Optional[Dict[str, str]]:
        return self.rows.get(str(transaction_id).lower())


def find_key_recursive(obj: Any, wanted_norms: set, path: str = "") -> List[Tuple[str, str, Any]]:
    """Return [(path, actual_key, value)] for every key whose normalised
    form is in wanted_norms, walking nested dicts/lists."""
    hits: List[Tuple[str, str, Any]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            child_path = f"{path}.{key}" if path else str(key)
            if norm_key(key) in wanted_norms:
                hits.append((child_path, key, value))
            hits.extend(find_key_recursive(value, wanted_norms, child_path))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            hits.extend(find_key_recursive(item, wanted_norms, f"{path}[{idx}]"))
    return hits


def find_scalar(obj: Any, wanted_norms: List[str]) -> Optional[Any]:
    """First scalar value whose key matches wanted_norms (in preference order)."""
    hits = find_key_recursive(obj, set(wanted_norms))
    scalars = [(k, v) for _, k, v in hits if not isinstance(v, (dict, list)) and not is_missing(v)]
    if not scalars:
        return None
    for wanted in wanted_norms:
        for key, value in scalars:
            if norm_key(key) == wanted:
                return value
    return scalars[0][1]


class ReferenceModel:
    """Learned shape of RetailSessionData from healthy (non-Trade) events."""

    def __init__(self):
        self.session_key: str = "RetailSessionData"
        self.field_casing: Dict[str, str] = {f: f for f in TARGET_FIELDS}
        self.parent_paths: Counter = Counter()
        self.samples_seen = 0

    def learn(self, event: Dict[str, Any]) -> None:
        hits = find_key_recursive(event, {RETAIL_SESSION_KEY_NORM})
        for path, actual_key, value in hits:
            if not isinstance(value, dict):
                continue
            self.samples_seen += 1
            self.session_key = actual_key
            parent = path.rsplit(".", 1)[0] if "." in path else "<root>"
            self.parent_paths[parent] += 1
            for field in TARGET_FIELDS:
                for existing_key in value:
                    if norm_key(existing_key) == norm_key(field):
                        self.field_casing[field] = existing_key

    def summary(self) -> str:
        if not self.samples_seen:
            return "no reference RetailSessionData blocks found; using canonical defaults"
        return (
            f"{self.samples_seen} reference block(s); key='{self.session_key}', "
            f"most common parent={self.parent_paths.most_common(1)[0][0]}, "
            f"field casing={self.field_casing}"
        )


class Stats:
    def __init__(self):
        self.files_scanned = 0
        self.files_changed = 0
        self.lines_total = 0
        self.lines_unparseable = 0
        self.events_by_type: Counter = Counter()
        self.affected_events = 0
        self.events_out_of_window = 0
        self.events_fixed = 0
        self.events_already_ok = 0
        self.events_unfixable = 0
        self.fields_filled_from_csv: Counter = Counter()
        self.fields_filled_from_payload: Counter = Counter()
        self.fields_unresolved: Counter = Counter()
        self.txn_ids_not_in_csv: set = set()


class Backfiller:
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.csv_lookup = CsvLookup(config.csv_file, logger) if config.csv_file else None
        self.reference = ReferenceModel()
        self.stats = Stats()
        self.affected_norms = {norm_key(t): t for t in config.affected_event_types}
        self.changes: List[Dict[str, str]] = []

    # ------------------------------------------------------------------ files

    def discover_files(self) -> List[str]:
        files: List[str] = []
        for pattern in self.config.input_globs:
            full = os.path.join(self.config.input_dir, pattern)
            files.extend(p for p in glob.glob(full, recursive=True) if os.path.isfile(p))
        files = sorted(set(files))
        self.logger.info("Discovered %d input file(s) under %s", len(files), self.config.input_dir)
        return files

    @staticmethod
    def _open_text(path: str):
        if path.endswith(".gz"):
            return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8")
        return open(path, "r", encoding="utf-8")

    @staticmethod
    def _parse_line(line: str) -> Tuple[Optional[Dict[str, Any]], str, str]:
        """Parse one structured-input line.

        Events are JSON objects, but some feeds prefix each line with
        delimited metadata before the JSON payload. Returns
        (event_dict, prefix, suffix) so the line can be reassembled
        byte-for-byte around the updated JSON, or (None, '', '') when no
        JSON object is present.
        """
        stripped = line.rstrip("\r\n")
        if not stripped.strip():
            return None, "", ""
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end < start:
            return None, "", ""
        candidate = stripped[start : end + 1]
        try:
            obj = json.loads(candidate, object_pairs_hook=OrderedDict)
        except json.JSONDecodeError:
            return None, "", ""
        if not isinstance(obj, dict):
            return None, "", ""
        return obj, stripped[:start], stripped[end + 1 :]

    # ------------------------------------------------------------------ events

    def event_type(self, event: Dict[str, Any]) -> Optional[str]:
        value = find_scalar(event, list(EVENT_TYPE_KEYS))
        return str(value) if value is not None else None

    def transaction_id(self, event: Dict[str, Any]) -> Optional[str]:
        value = find_scalar(event, list(TRANSACTION_ID_KEYS))
        return str(value) if value is not None else None

    def in_date_window(self, event: Dict[str, Any]) -> bool:
        if self.config.date_from is None and self.config.date_to is None:
            return True
        raw = find_scalar(event, DEFAULT_PAYLOAD_FALLBACK_KEYS["UTCTimestamp"])
        try:
            ts = int(float(str(raw)))
        except (TypeError, ValueError):
            return True  # cannot tell; do not silently skip
        if ts > 10**12:  # millisecond epoch
            ts //= 1000
        if self.config.date_from is not None and ts < self.config.date_from:
            return False
        if self.config.date_to is not None and ts > self.config.date_to:
            return False
        return True

    def _get_or_create_session_block(self, event: Dict[str, Any]) -> Dict[str, Any]:
        hits = find_key_recursive(event, {RETAIL_SESSION_KEY_NORM})
        for _, _, value in hits:
            if isinstance(value, dict):
                return value
        # Replace a null/empty placeholder in place if one exists.
        if hits:
            container_hits = self._find_parent_containers(event)
            for parent, key in container_hits:
                if norm_key(key) == RETAIL_SESSION_KEY_NORM and not isinstance(parent[key], dict):
                    parent[key] = OrderedDict()
                    return parent[key]
        # No block at all: create it at the event root using the learned key.
        event[self.reference.session_key] = OrderedDict()
        return event[self.reference.session_key]

    @staticmethod
    def _find_parent_containers(obj: Any) -> List[Tuple[Dict[str, Any], str]]:
        found: List[Tuple[Dict[str, Any], str]] = []
        if isinstance(obj, dict):
            for key, value in obj.items():
                if norm_key(key) == RETAIL_SESSION_KEY_NORM:
                    found.append((obj, key))
                found.extend(Backfiller._find_parent_containers(value))
        elif isinstance(obj, list):
            for item in obj:
                found.extend(Backfiller._find_parent_containers(item))
        return found

    def _resolve_value(
        self, field: str, event: Dict[str, Any], csv_row: Optional[Dict[str, str]]
    ) -> Tuple[Optional[str], str]:
        """Return (value, source) for a target field: CSV first, then payload."""
        if csv_row is not None:
            value = csv_row.get(field, "")
            if not is_missing(value):
                return value, "csv"
        if self.config.allow_payload_fallback:
            value = find_scalar(event, DEFAULT_PAYLOAD_FALLBACK_KEYS[field])
            if value is not None:
                return str(value), "payload"
        return None, "unresolved"

    def fix_event(self, event: Dict[str, Any], file_path: str, line_no: int) -> bool:
        """Backfill one affected event in place. Returns True if modified."""
        session = self._get_or_create_session_block(event)

        # Map already-present keys tolerant of casing.
        present = {norm_key(k): k for k in session}

        txn_id = self.transaction_id(event)
        csv_row = None
        if self.csv_lookup and txn_id:
            csv_row = self.csv_lookup.get(txn_id)
            if csv_row is None:
                self.stats.txn_ids_not_in_csv.add(txn_id)

        modified = False
        unresolved = []
        for field in TARGET_FIELDS:
            existing_key = present.get(norm_key(field))
            if existing_key is not None and not is_missing(session[existing_key]):
                continue  # already populated
            value, source = self._resolve_value(field, event, csv_row)
            if value is None:
                unresolved.append(field)
                self.stats.fields_unresolved[field] += 1
                continue
            write_key = existing_key or self.reference.field_casing[field]
            session[write_key] = value
            modified = True
            if source == "csv":
                self.stats.fields_filled_from_csv[field] += 1
            else:
                self.stats.fields_filled_from_payload[field] += 1
            self.changes.append(
                {
                    "file": file_path,
                    "line": str(line_no),
                    "transaction_id": txn_id or "",
                    "event_type": self.event_type(event) or "",
                    "field": write_key,
                    "value": value,
                    "source": source,
                }
            )

        if unresolved:
            self.stats.events_unfixable += 1
            self.logger.warning(
                "%s:%d txn=%s - could not resolve %s (not in CSV, not in payload)",
                file_path,
                line_no,
                txn_id,
                unresolved,
            )
        return modified

    # ------------------------------------------------------------------ passes

    def learn_pass(self, files: List[str]) -> None:
        """Pass 1: learn RetailSessionData shape from healthy reference events."""
        for path in files:
            try:
                with self._open_text(path) as fh:
                    for line in fh:
                        event, _, _ = self._parse_line(line)
                        if event is None:
                            continue
                        etype = self.event_type(event)
                        if etype and norm_key(etype) in self.affected_norms:
                            continue
                        self.reference.learn(event)
            except (OSError, UnicodeDecodeError) as exc:
                self.logger.warning("Skipping unreadable file %s: %s", path, exc)
        self.logger.info("Reference model: %s", self.reference.summary())

    def process_pass(self, files: List[str]) -> None:
        """Pass 2: inspect / fix affected Trade events."""
        write_enabled = self.config.mode == "apply"
        for path in files:
            self.stats.files_scanned += 1
            out_lines: List[str] = []
            file_changed = False
            try:
                with self._open_text(path) as fh:
                    for line_no, line in enumerate(fh, start=1):
                        newline = "\n" if line.endswith("\n") else ""
                        self.stats.lines_total += 1
                        event, prefix, suffix = self._parse_line(line)
                        if event is None:
                            if line.strip():
                                self.stats.lines_unparseable += 1
                            out_lines.append(line)
                            continue

                        etype = self.event_type(event)
                        self.stats.events_by_type[etype or "<unknown>"] += 1

                        if not etype or norm_key(etype) not in self.affected_norms:
                            out_lines.append(line)
                            continue

                        self.stats.affected_events += 1
                        if not self.in_date_window(event):
                            self.stats.events_out_of_window += 1
                            out_lines.append(line)
                            continue

                        if self.config.mode == "inspect":
                            self._inspect_event(event, path, line_no)
                            out_lines.append(line)
                            continue

                        if self.fix_event(event, path, line_no):
                            self.stats.events_fixed += 1
                            file_changed = True
                            out_lines.append(
                                prefix
                                + json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                                + suffix
                                + newline
                            )
                        else:
                            self.stats.events_already_ok += 1
                            out_lines.append(line)
            except (OSError, UnicodeDecodeError) as exc:
                self.logger.warning("Skipping unreadable file %s: %s", path, exc)
                continue

            if file_changed:
                self.stats.files_changed += 1
                if write_enabled:
                    self._write_file(path, out_lines)

    def _inspect_event(self, event: Dict[str, Any], path: str, line_no: int) -> None:
        hits = find_key_recursive(event, {RETAIL_SESSION_KEY_NORM})
        session = next((v for _, _, v in hits if isinstance(v, dict)), None)
        if session is None:
            missing = list(TARGET_FIELDS)
        else:
            present = {norm_key(k) for k, v in session.items() if not is_missing(v)}
            missing = [f for f in TARGET_FIELDS if norm_key(f) not in present]
        if missing:
            self.logger.info(
                "%s:%d %s txn=%s missing=%s",
                path,
                line_no,
                self.event_type(event),
                self.transaction_id(event),
                missing,
            )

    def _write_file(self, path: str, out_lines: List[str]) -> None:
        if self.config.in_place:
            target = path
            if self.config.keep_backups:
                backup = path + ".bak"
                if not os.path.exists(backup):
                    os.replace(path, backup)
                else:
                    self.logger.warning("Backup already exists, not overwriting: %s", backup)
        else:
            rel = os.path.relpath(path, self.config.input_dir)
            target = os.path.join(self.config.output_dir, "fixed", rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)

        if target.endswith(".gz"):
            with gzip.open(target, "wt", encoding="utf-8") as fh:
                fh.writelines(out_lines)
        else:
            with open(target, "w", encoding="utf-8") as fh:
                fh.writelines(out_lines)
        self.logger.info("Wrote updated file: %s", target)

    # ------------------------------------------------------------------ report

    def write_report(self) -> None:
        os.makedirs(self.config.output_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if self.changes:
            changes_path = os.path.join(
                self.config.output_dir, f"backfill_changes_{self.config.mode}_{stamp}.csv"
            )
            with open(changes_path, "w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(
                    fh,
                    fieldnames=[
                        "file", "line", "transaction_id", "event_type",
                        "field", "value", "source",
                    ],
                )
                writer.writeheader()
                writer.writerows(self.changes)
            self.logger.info("Change report: %s (%d field fills)", changes_path, len(self.changes))

        if self.stats.txn_ids_not_in_csv:
            missing_path = os.path.join(
                self.config.output_dir, f"backfill_txn_not_in_csv_{stamp}.csv"
            )
            with open(missing_path, "w", encoding="utf-8", newline="") as fh:
                fh.write("TransactionId\n")
                for txn in sorted(self.stats.txn_ids_not_in_csv):
                    fh.write(f"{txn}\n")
            self.logger.info(
                "TransactionIds missing from CSV: %s (%d ids)",
                missing_path,
                len(self.stats.txn_ids_not_in_csv),
            )

    def log_summary(self) -> None:
        s = self.stats
        self.logger.info("=" * 70)
        self.logger.info("SUMMARY (%s mode) - tenant %s", self.config.mode, self.config.tenant_name)
        self.logger.info("Files scanned:          %d", s.files_scanned)
        self.logger.info("Files with changes:     %d", s.files_changed)
        self.logger.info("Lines total:            %d", s.lines_total)
        self.logger.info("Lines unparseable:      %d", s.lines_unparseable)
        self.logger.info("Events by type:         %s", dict(s.events_by_type))
        self.logger.info("Affected Trade events:  %d", s.affected_events)
        self.logger.info("  outside date window:  %d", s.events_out_of_window)
        if self.config.mode != "inspect":
            self.logger.info("  fixed:                %d", s.events_fixed)
            self.logger.info("  already complete:     %d", s.events_already_ok)
            self.logger.info("  with unresolved:      %d", s.events_unfixable)
            self.logger.info("Fields from CSV:        %s", dict(s.fields_filled_from_csv))
            self.logger.info("Fields from payload:    %s", dict(s.fields_filled_from_payload))
            self.logger.info("Fields unresolved:      %s", dict(s.fields_unresolved))
        self.logger.info("Txn ids not in CSV:     %d", len(s.txn_ids_not_in_csv))
        if self.config.mode == "dry-run":
            self.logger.info("Dry-run: no files were modified. Set mode = apply to write.")
        self.logger.info("=" * 70)

    def run(self) -> int:
        files = self.discover_files()
        if not files:
            self.logger.error("No input files found - check [INPUT] input_dir / input_glob")
            return 1
        self.learn_pass(files)
        self.process_pass(files)
        self.write_report()
        self.log_summary()
        return 0


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        print("Usage: python backfill_missing_fields.py <config.ini>")
        return 2
    config = Config(sys.argv[1])
    os.makedirs(config.output_dir, exist_ok=True)
    log_manager = LogManager(
        log_dir=os.path.join(config.output_dir, "logs"),
        log_level=logging.INFO,
        tenant_name=config.tenant_name,
    )
    logger = log_manager.get_logger()
    logger.info("Backfill starting: mode=%s input=%s", config.mode, config.input_dir)
    backfiller = Backfiller(config, logger)
    return backfiller.run()


if __name__ == "__main__":
    sys.exit(main())
