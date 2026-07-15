"""
Field definitions and extraction helpers for Questrade RetailSessionData.

Missing fields on TradeDelete / TradeEdit / TradeSubmit are populated from:
1. Enrichment CSV keyed by TransactionId (primary)
2. Existing event payload paths used by reference events (fallback)
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional

# Events that currently omit RetailSessionData session fields.
TARGET_EVENT_TYPES = frozenset({"TradeDelete", "TradeEdit", "TradeSubmit"})

# Fields Questrade requires inside RetailSessionData.
REQUIRED_SESSION_FIELDS = (
    "UTCTimestamp",
    "ImmutableUserID",
    "IPAddress",
    "SignOnId",
    "UserAgentString",
)

# CSV column names (after whitespace normalization).
CSV_FIELD_ALIASES = {
    "transactionid": "TransactionId",
    "channel": "Channel",
    "utctimestamp": "UTCTimestamp",
    "immutableuserid": "ImmutableUserID",
    "ipaddress": "IPAddress",
    "signonid": "SignOnId",
    "useragentstring": "UserAgentString",
}

# Payload fallback paths observed on reference events that already carry
# RetailSessionData. First match wins for each target field.
PAYLOAD_FALLBACK_PATHS: Dict[str, List[List[str]]] = {
    "UTCTimestamp": [
        ["RetailSessionData", "UTCTimestamp"],
        ["UTCTimestamp"],
        ["EventTimestamp"],
        ["Timestamp"],
        ["payload", "UTCTimestamp"],
        ["payload", "timestamp"],
        ["session", "UTCTimestamp"],
    ],
    "ImmutableUserID": [
        ["RetailSessionData", "ImmutableUserID"],
        ["ImmutableUserID"],
        ["UserId"],
        ["UserID"],
        ["payload", "ImmutableUserID"],
        ["payload", "userId"],
        ["payload", "user", "id"],
        ["session", "ImmutableUserID"],
    ],
    "IPAddress": [
        ["RetailSessionData", "IPAddress"],
        ["IPAddress"],
        ["ClientIP"],
        ["ip"],
        ["payload", "IPAddress"],
        ["payload", "clientIp"],
        ["payload", "network", "ip"],
        ["session", "IPAddress"],
    ],
    "SignOnId": [
        ["RetailSessionData", "SignOnId"],
        ["SignOnId"],
        ["SessionId"],
        ["SessionID"],
        ["payload", "SignOnId"],
        ["payload", "sessionId"],
        ["payload", "session", "id"],
        ["session", "SignOnId"],
    ],
    "UserAgentString": [
        ["RetailSessionData", "UserAgentString"],
        ["UserAgentString"],
        ["UserAgent"],
        ["payload", "UserAgentString"],
        ["payload", "userAgent"],
        ["payload", "device", "userAgent"],
        ["session", "UserAgentString"],
    ],
    "Channel": [
        ["RetailSessionData", "Channel"],
        ["Channel"],
        ["payload", "Channel"],
        ["payload", "channel"],
    ],
}


def normalize_csv_header(name: str) -> str:
    """Normalize CSV header whitespace and map known aliases."""
    cleaned = (name or "").strip()
    key = cleaned.replace(" ", "").lower()
    return CSV_FIELD_ALIASES.get(key, cleaned)


def get_nested(obj: Any, path: Iterable[str]) -> Any:
    """Return nested value for path, or None if missing."""
    current = obj
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def set_nested(obj: MutableMapping[str, Any], path: List[str], value: Any) -> None:
    """Set nested value, creating intermediate dicts as needed."""
    current: MutableMapping[str, Any] = obj
    for part in path[:-1]:
        next_val = current.get(part)
        if not isinstance(next_val, MutableMapping):
            next_val = {}
            current[part] = next_val
        current = next_val
    current[path[-1]] = value


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def event_type_of(event: Mapping[str, Any]) -> str:
    for path in (
        ["EventType"],
        ["eventType"],
        ["event_type"],
        ["Type"],
        ["type"],
        ["event", "type"],
        ["payload", "EventType"],
        ["payload", "eventType"],
    ):
        value = get_nested(event, path)
        if not is_blank(value):
            return str(value).strip()
    return ""


def transaction_id_of(event: Mapping[str, Any]) -> str:
    for path in (
        ["TransactionId"],
        ["transactionId"],
        ["transaction_id"],
        ["event", "id"],
        ["EventId"],
        ["id"],
        ["payload", "TransactionId"],
        ["payload", "transactionId"],
    ):
        value = get_nested(event, path)
        if not is_blank(value):
            return str(value).strip()
    return ""


def extract_from_payload(event: Mapping[str, Any], field: str) -> Any:
    """Extract a session field from known payload paths (reference-event style)."""
    for path in PAYLOAD_FALLBACK_PATHS.get(field, []):
        value = get_nested(event, path)
        if not is_blank(value):
            return value
    return None


def resolve_session_value(
    field: str,
    csv_row: Optional[Mapping[str, Any]],
    event: Mapping[str, Any],
) -> Any:
    """
    Resolve one RetailSessionData field.

    Preference order:
    1. Non-blank CSV column
    2. Existing payload / reference-style path
    """
    if csv_row is not None:
        csv_value = csv_row.get(field)
        if not is_blank(csv_value):
            return csv_value
    return extract_from_payload(event, field)


def build_retail_session_data(
    event: Mapping[str, Any],
    csv_row: Optional[Mapping[str, Any]] = None,
    include_channel: bool = True,
) -> Dict[str, Any]:
    """
    Build RetailSessionData hash for an event.

    Starts from any existing RetailSessionData, then fills required fields
    from CSV and/or payload fallbacks so trade events match reference events.
    """
    existing = event.get("RetailSessionData")
    session: Dict[str, Any] = dict(existing) if isinstance(existing, Mapping) else {}

    fields = list(REQUIRED_SESSION_FIELDS)
    if include_channel:
        fields.append("Channel")

    for field in fields:
        if not is_blank(session.get(field)):
            continue
        value = resolve_session_value(field, csv_row, event)
        if not is_blank(value):
            # Keep timestamps as strings/ints as provided (CSV epoch is fine).
            session[field] = value

    return session


def missing_required_fields(session: Mapping[str, Any]) -> List[str]:
    return [f for f in REQUIRED_SESSION_FIELDS if is_blank(session.get(f))]
