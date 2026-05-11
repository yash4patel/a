import codecs
import glob
import json
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List

import chardet
import pandas as pd

from log_manager import (
    check_results,
    log_check,
    log_footer,
    log_header,
    log_individual_check_results,
    log_section_end,
    log_section_start,
    log_summary,
)

# X9 Field Definitions
X9_FIELDS = {
    "01": {
        "standard_level": (3, 5),
        "test_file_indicator": (5, 6),
        "immediate_destination_routing_number": (6, 15),
        "immediate_origin_routing_number": (15, 24),
        "file_creation_date": (24, 32),
        "file_creation_time": (32, 36),
        "resend_indicator": (36, 37),
        "immediate_destination_name": (37, 55),
        "immediate_origin_name": (55, 73),
        "file_id_modifier": (73, 74),
        "country_code": (74, 76),
    },
    "10": {
        "collection_type_indicator": (3, 5),
        "destination_routing_number": (5, 14),
        "ece_institution_routing_number": (14, 23),
        "cash_letter_business_date": (23, 31),
        "cash_letter_creation_date": (31, 39),
        "cash_letter_creation_time": (39, 43),
        "cash_letter_record_type_indicator": (43, 44),
        "cash_letter_documentation_type_indicator": (44, 45),
        "cash_letter_id": (45, 53),
        "originator_contact_name": (53, 67),
        "originator_contact_phone_number": (67, 77),
        "fed_work_type": (77, 78),
    },
    "20": {
        "collection_type_indicator": (3, 5),
        "bundle_destination_routing_number": (5, 14),
        "bundle_ece_institution_routing_number": (14, 23),
        "bundle_business_date": (23, 31),
        "bundle_creation_Date": (31, 39),
        "bundle_id": (39, 49),
        "bundle_sequence_number": (49, 53),
        "cycle_number": (53, 55),
        "return_location_routing_number": (55, 64),
    },
    "25": {
        "auxiliary_on_us": (3, 18),
        "external_processing_code": (18, 19),
        "payor_bank_routing_number": (19, 27),
        "payor_bank_routing_number_check_digit": (27, 28),
        "on_us": (28, 48),
        "item_amount": (48, 58),
        "ece_institution_item_sequence_number": (58, 73),
        "documentation_type_indicator": (73, 74),
        "electronic_return_acceptance_indicator": (74, 75),
        "micr_valid_indicator": (75, 76),
        "bofd_indicator": (76, 77),
        "check_detail_record_addendum_count": (77, 79),
        "correction_indicator": (79, 80),
        "archive_type_indicator": (80, 81),
    },
    "26": {
        "check_detail_addendum_a_record_number": (3, 4),
        "bofd_routing_number": (4, 13),
        "bofd_business_date": (13, 21),
        "bofd_item_sequence_number": (21, 36),
        "deposit_account_number_at_bofd": (36, 54),
        "bofd_deposit_branch": (54, 59),
        "payee_name": (59, 74),
        "truncator_indicator": (74, 75),
        "bofd_conversion_indicator": (75, 76),
        "bofd_correction_indicator": (76, 77),
    },
    "28": {
        "check_detail_addendum_c_record_number": (3, 5),
        "endorsing_bank_routing_number": (5, 14),
        "endorsing_bank_endorsement_date": (14, 22),
        "endorsing_bank_item_sequence_number": (22, 37),
        "truncation_indicator": (37, 38),
        "endorsing_bank_conversion_indicator": (38, 39),
        "endorsing_bank_correction_indicator": (39, 40),
        "return_reason": (40, 41),
    },
    "31": {
        "payor_bank_routing_number": (3, 11),
        "payor_bank_routing_number_check_digit": (11, 12),
        "on_us_return_record": (12, 32),
        "item_amount": (32, 42),
        "return_reason": (42, 43),
        "return_record_addendum_count": (43, 45),
        "return_document_type_indicator": (45, 46),
        "forward_bundle_date": (46, 54),
        "ece_institution_item_sequence_number": (54, 69),
        "external_processing_code": (69, 70),
        "return_notification_indicator": (70, 71),
        "return_archive_type_indicator": (71, 72),
    },
    "32": {
        "bofd_routing_number": (4, 13),
        "bofd_business_date": (13, 21),
        "bofd_item_sequence_number": (21, 36),
        "deposit_account_number_at_bofd": (36, 54),
        "bofd_deposit_branch": (54, 59),
        "payee_name": (59, 74),
        "truncation_indicator": (74, 75),
        "bofd_conversion_indicator": (75, 76),
        "bofd_correction_indicator": (76, 77),
    },
    "33": {
        "payor_bank_name": (3, 21),
        "auxiliary_onus": (21, 36),
        "payor_bank_item_sequence_number": (36, 51),
        "payor_bank_business_date": (51, 59),
        "payor_account_name": (59, 71),
    },
    "35": {
        "return_addendum_d_record_number": (3, 5),
        "endorsing_bank_routing_number": (5, 14),
        "endorsing_bank_endorsement_date": (14, 22),
        "endorsing_bank_item_sequence_number": (22, 37),
        "truncation_indicator": (37, 38),
        "endorsing_bank_conversion_indicator": (38, 39),
        "endorsing_bank_correction_indicator": (39, 40),
        "return_reason": (40, 41),
    },
    # Minimal control-record slices used for required record and critical field checks.
    "50": {
        "cash_letter_item_count": (3, 11),
        "cash_letter_amount_total": (11, 23),
    },
    "52": {
        "bundle_item_count": (3, 11),
        "bundle_amount_total": (11, 23),
    },
}

HEADER_SEQUENCE = ("01", "10", "20")
PRESENTMENT_REQUIRED_TYPES = ("25", "26", "50", "52")
RETURN_REQUIRED_TYPES = ("31", "32", "50", "52")
TRACKED_RECORD_TYPES = ("25", "26", "31", "32", "50", "52")
MAX_ISSUES_PER_FILE = 120
X937_VALID_RECORD_TYPES = (
    "01",
    "10",
    "20",
    "25",
    "26",
    "28",
    "31",
    "32",
    "33",
    "35",
    "50",
    "52",
    "54",
    "61",
    "62",
    "70",
    "90",
    "99",
)


def get_record_type(line: str) -> str:
    """Return X9 record type from one line."""
    if not line or len(line) < 3:
        return ""
    return line[1:3]


def get_record_type_values(line: str):
    """Extract field values from a line based on record type."""
    record_type = get_record_type(line)
    if record_type not in X9_FIELDS:
        return {}
    fields = X9_FIELDS[record_type]
    result = {}
    for key, value in fields.items():
        result[f"{record_type}_{key}"] = line[value[0] : value[1]]
    return result


def _slice(line: str, start: int, end: int = None) -> str:
    """Safe string slice with stripping."""
    if len(line) <= start:
        return ""
    if end is None:
        return line[start:].strip()
    return line[start:end].strip()


def _normalize_scalar_text(value: Any) -> str:
    """Normalize scalar text values and collapse null-like tokens to empty."""
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null", "<na>"}:
        return ""
    text = text.strip("\"'").strip()
    return "" if not text else text


def _normalize_text_series(df: pd.DataFrame, column: str) -> pd.Series:
    """Return normalized text series for a dataframe column."""
    if column not in df.columns:
        return pd.Series("", index=df.index, dtype="string")
    series = df[column].astype("string").fillna("").str.strip()
    series = series.str.strip("\"'").str.strip()
    return series.replace(r"(?i)^(nan|none|null|<na>)$", "", regex=True)


def _unique_non_empty(values: pd.Series, limit: int = 5) -> List[str]:
    """Extract first unique non-empty normalized values from a series."""
    unique = []
    for value in values:
        text = _normalize_scalar_text(value)
        if not text or text in unique:
            continue
        unique.append(text)
        if len(unique) >= limit:
            break
    return unique


def _is_valid_aba_routing(routing9: str) -> bool:
    """Validate ABA routing using checksum (3-7-1 weighting)."""
    if len(routing9) != 9 or not routing9.isdigit():
        return False
    weights = [3, 7, 1, 3, 7, 1, 3, 7, 1]
    checksum = sum(int(d) * w for d, w in zip(routing9, weights))
    return checksum % 10 == 0


def _infer_image_side_from_50(line: str) -> str:
    """Infer FRONT/BACK/UNKNOWN from type 50 metadata."""
    raw_upper = line.upper()
    if "FRONT" in raw_upper:
        return "FRONT"
    if "BACK" in raw_upper:
        return "BACK"

    # Heuristic based on common side-indicator positions/values.
    for pos in (31, 32, 33):
        if len(line) > pos:
            marker = line[pos].strip().upper()
            if marker in {"0", "F"}:
                return "FRONT"
            if marker in {"1", "B"}:
                return "BACK"
    return "UNKNOWN"


def _infer_image_format(meta_50_line: str, data_52_line: str) -> str:
    """Infer TIFF/NON_TIFF/UNKNOWN based on metadata and bytes hints."""
    meta_upper = meta_50_line.upper()
    data_upper = _slice(data_52_line, 3).upper()

    non_tiff_tokens = ("JPEG", "JPG", "PNG", "GIF", "BMP", "PDF", "FFD8FF", "89504E47", "47494638", "25504446")
    tiff_tokens = ("TIFF", "TIF", "49492A00", "4D4D002A")

    if any(token in meta_upper for token in non_tiff_tokens) or any(
        token in data_upper for token in non_tiff_tokens
    ):
        return "NON_TIFF"
    if any(token in meta_upper for token in tiff_tokens) or any(token in data_upper for token in tiff_tokens):
        return "TIFF"

    # Common format indicator value where 0 typically means TIFF.
    if len(meta_50_line) > 21 and meta_50_line[21].strip() == "0":
        return "TIFF"
    return "UNKNOWN"


def _extract_check_context_from_25(line: str) -> Dict[str, str]:
    """Extract check-identifying fields from record 25 for pinpoint reporting."""
    aux_on_us = _slice(line, 3, 18)
    on_us = _slice(line, 28, 48)
    item_seq = _slice(line, 58, 73)

    on_us_clean = on_us.strip("/")
    on_us_parts = [p for p in on_us_clean.split("/") if p]
    payer_account = on_us_parts[0] if on_us_parts else ""
    check_number = aux_on_us if aux_on_us else (on_us_parts[-1] if on_us_parts else "")

    return {
        "payer_account": payer_account,
        "check_number": check_number,
        "on_us": on_us,
        "aux_on_us": aux_on_us,
        "item_sequence_number": item_seq,
    }


def validate_critical_fields_for_record(line: str, record_type: str, line_number: int):
    """Validate critical fields (RT/account/MICR/image presence) by record type."""
    issues = []

    if record_type == "25":
        aux_on_us = _slice(line, 3, 18)
        payor_rt = _slice(line, 19, 27)
        payor_cd = _slice(line, 27, 28)
        on_us = _slice(line, 28, 48)
        item_amount = _slice(line, 48, 58)
        if not aux_on_us:
            issues.append(f"Record 25 line {line_number}: missing AUX_ON_US")
        if not payor_rt or not payor_rt.isdigit() or len(payor_rt) != 8:
            issues.append(
                f"Record 25 line {line_number}: invalid/missing payor_bank_routing_number (8 digits required)"
            )
        if not payor_cd or not payor_cd.isdigit() or len(payor_cd) != 1:
            issues.append(
                f"Record 25 line {line_number}: invalid/missing payor_bank_routing_number_check_digit (1 digit required)"
            )
        if payor_rt.isdigit() and len(payor_rt) == 8 and payor_cd.isdigit() and len(payor_cd) == 1:
            if not _is_valid_aba_routing(payor_rt + payor_cd):
                issues.append(
                    f"Record 25 line {line_number}: invalid ABA routing checksum for {payor_rt + payor_cd}"
                )
        if not on_us:
            issues.append(f"Record 25 line {line_number}: missing ON_US (MICR) data")
        micr_line = f"{aux_on_us}{on_us}".strip()
        if not micr_line:
            issues.append(f"Record 25 line {line_number}: missing MICR line")
        if not item_amount or not item_amount.isdigit():
            issues.append(f"Record 25 line {line_number}: missing/invalid item_amount")

    elif record_type == "26":
        bofd_rt = _slice(line, 4, 13)
        bofd_business_date = _slice(line, 13, 21)
        bofd_item_seq = _slice(line, 21, 36)
        bofd_account = _slice(line, 36, 54)
        if not bofd_rt or not bofd_rt.isdigit() or len(bofd_rt) != 9:
            issues.append(f"Record 26 line {line_number}: invalid/missing bofd_routing_number (9 digits required)")
        elif not _is_valid_aba_routing(bofd_rt):
            issues.append(f"Record 26 line {line_number}: invalid ABA routing checksum for {bofd_rt}")
        if not bofd_business_date or not bofd_business_date.isdigit() or len(bofd_business_date) != 8:
            issues.append(f"Record 26 line {line_number}: missing/invalid bofd_business_date (YYYYMMDD required)")
        if not bofd_item_seq:
            issues.append(f"Record 26 line {line_number}: missing bofd_item_sequence_number")
        # Deposit account requirement is validated conditionally in Phase 2:
        # mandatory for deposits, optional for withdrawals.

    elif record_type == "31":
        payor_rt = _slice(line, 3, 11)
        payor_cd = _slice(line, 11, 12)
        on_us_return = _slice(line, 12, 32)
        item_amount = _slice(line, 32, 42)
        if not payor_rt or not payor_rt.isdigit() or len(payor_rt) != 8:
            issues.append(
                f"Record 31 line {line_number}: invalid/missing payor_bank_routing_number (8 digits required)"
            )
        if not payor_cd or not payor_cd.isdigit() or len(payor_cd) != 1:
            issues.append(
                f"Record 31 line {line_number}: invalid/missing payor_bank_routing_number_check_digit (1 digit required)"
            )
        if payor_rt.isdigit() and len(payor_rt) == 8 and payor_cd.isdigit() and len(payor_cd) == 1:
            if not _is_valid_aba_routing(payor_rt + payor_cd):
                issues.append(
                    f"Record 31 line {line_number}: invalid ABA routing checksum for {payor_rt + payor_cd}"
                )
        if not on_us_return:
            issues.append(f"Record 31 line {line_number}: missing ON_US_RETURN_RECORD (MICR) data")
        if not item_amount or not item_amount.isdigit():
            issues.append(f"Record 31 line {line_number}: missing/invalid item_amount")

    elif record_type == "32":
        bofd_rt = _slice(line, 4, 13)
        bofd_account = _slice(line, 36, 54)
        if not bofd_rt or not bofd_rt.isdigit() or len(bofd_rt) != 9:
            issues.append(f"Record 32 line {line_number}: invalid/missing bofd_routing_number (9 digits required)")
        elif not _is_valid_aba_routing(bofd_rt):
            issues.append(f"Record 32 line {line_number}: invalid ABA routing checksum for {bofd_rt}")
        if not bofd_account:
            issues.append(f"Record 32 line {line_number}: missing deposit_account_number_at_bofd")

    elif record_type in {"50", "52"}:
        # Deep image metadata/bytes validation intentionally skipped.
        # We only validate record-type presence for image records.
        pass

    return issues


def validate_x937_file_structure(records: List[str], file_name: str) -> Dict:
    """
    Phase 1 - Basic Validation:
    1) File must begin with 01 -> 10 -> 20.
    2) Enforce 25/26 ordering: 26 must follow 25 and each 25 must have a 26.
    3) Enforce required record types by collection mode:
       - Presentment (01 / 25+26): require 25/26/50/52.
       - Return (03 / 31+32): require 31/32/50/52.
       Return mode is optional (absence does not fail).
    4) Critical fields must be populated (routing/account/MICR/image fields).
    5) Per check item (25 and 31), require at least one record 50 (image view detail).
       Missing 52 is tracked as image-block completeness advisory.
    """
    issues = []
    header_ok = False
    orphan_26_count = 0
    missing_26_after_25_count = 0
    rec25_total = 0
    rec26_total = 0
    record_type_counts = {rt: 0 for rt in TRACKED_RECORD_TYPES}
    collection_type_values = set()
    return_records_present = False
    critical_field_error_count = 0
    dropped_issue_count = 0

    presentment_item_count = 0
    presentment_items_without_image_pair = 0
    presentment_items_without_front_image = 0
    presentment_items_non_tiff = 0

    return_item_count = 0
    return_items_without_image_pair = 0
    return_items_without_front_image = 0
    return_items_non_tiff = 0

    current_item = None
    current_cash_letter_id = ""
    current_cash_letter_business_date = ""
    current_bundle_id = ""
    current_bundle_business_date = ""
    current_bundle_sequence_number = ""
    open_25_context = None
    missing_26_details = []
    presentment_missing_front_examples = []
    return_missing_front_examples = []
    presentment_missing_pair_examples = []
    return_missing_pair_examples = []

    def add_issue(message: str):
        nonlocal dropped_issue_count
        if len(issues) < MAX_ISSUES_PER_FILE:
            issues.append(message)
        else:
            dropped_issue_count += 1

    def add_missing_26_detail(boundary_record_type: str, boundary_line: int, reason: str):
        """Capture pinpoint context for a 25 that did not receive a 26."""
        if not open_25_context:
            return
        missing_26_details.append(
            {
                "filename": file_name,
                "line_25": open_25_context["line_25"],
                "bundle_business_date": open_25_context["bundle_business_date"],
                "bundle_id": open_25_context["bundle_id"],
                "bundle_sequence_number": open_25_context["bundle_sequence_number"],
                "cash_letter_business_date": open_25_context["cash_letter_business_date"],
                "cash_letter_id": open_25_context["cash_letter_id"],
                "unique_check_id": open_25_context["unique_check_id"],
                "check_number": open_25_context["check_number"],
                "payer_account": open_25_context["payer_account"],
                "on_us": open_25_context["on_us"],
                "aux_on_us": open_25_context["aux_on_us"],
                "item_sequence_number": open_25_context["item_sequence_number"],
                "boundary_record_type": boundary_record_type,
                "boundary_line": boundary_line,
                "reason": reason,
            }
        )

    def finalize_current_item(reason: str):
        nonlocal current_item
        nonlocal presentment_item_count
        nonlocal return_item_count
        nonlocal presentment_items_without_front_image
        nonlocal return_items_without_front_image
        nonlocal presentment_items_without_image_pair
        nonlocal return_items_without_image_pair

        if current_item is None:
            return

        item_type = current_item["item_type"]
        image_50_count = int(current_item.get("image_50_count", 0))
        image_52_count = int(current_item.get("image_52_count", 0))
        unique_id = current_item.get("check_ref", {}).get("unique_check_id", "")

        is_presentment_item = item_type == "25"
        if is_presentment_item:
            presentment_item_count += 1
            if image_50_count == 0:
                presentment_items_without_front_image += 1
                if len(presentment_missing_front_examples) < 10:
                    presentment_missing_front_examples.append(unique_id)
            if image_50_count > 0 and image_52_count == 0:
                presentment_items_without_image_pair += 1
                if len(presentment_missing_pair_examples) < 10:
                    presentment_missing_pair_examples.append(unique_id)
        else:
            return_item_count += 1
            if image_50_count == 0:
                return_items_without_front_image += 1
                if len(return_missing_front_examples) < 10:
                    return_missing_front_examples.append(unique_id)
            if image_50_count > 0 and image_52_count == 0:
                return_items_without_image_pair += 1
                if len(return_missing_pair_examples) < 10:
                    return_missing_pair_examples.append(unique_id)

        current_item = None

    if len(records) >= 3:
        first_three = [get_record_type(records[0]), get_record_type(records[1]), get_record_type(records[2])]
        if first_three == list(HEADER_SEQUENCE):
            header_ok = True
        else:
            add_issue(
                f"Header sequence must start with 01->10->20, found {'->'.join(first_three)}"
            )
    else:
        add_issue("File does not have at least 3 records for required 01->10->20 header")

    open_25_line = None
    open_25_has_26 = False
    # Closing boundaries for a 25-item context.
    # If one of these appears and no 26 was seen, the preceding 25 is invalid.
    close_25_context = {"25", "31", "20", "10", "50", "52", "61", "62", "70", "90", "99", "01"}

    for idx, line in enumerate(records, start=1):
        rt = get_record_type(line)
        if rt == "10":
            cti = _slice(line, 3, 5)
            if cti:
                collection_type_values.add(cti)
            current_cash_letter_business_date = _slice(line, 23, 31)
            current_cash_letter_id = _slice(line, 45, 53)
        elif rt == "20":
            current_bundle_business_date = _slice(line, 23, 31)
            current_bundle_id = _slice(line, 39, 49)
            current_bundle_sequence_number = _slice(line, 49, 53)

        if rt in record_type_counts:
            record_type_counts[rt] += 1
        if rt in {"31", "32"}:
            return_records_present = True

        if rt in {"25", "26", "31", "32", "50", "52"}:
            critical_field_issues = validate_critical_fields_for_record(line, rt, idx)
            critical_field_error_count += len(critical_field_issues)
            for msg in critical_field_issues:
                add_issue(msg)

        # Start/end item contexts (for image pairing checks).
        if rt == "25":
            finalize_current_item(f"record 25 at line {idx}")
            check_ctx = _extract_check_context_from_25(line)
            check_ctx["unique_check_id"] = build_unique_check_id(
                file_name=file_name,
                item_type="25",
                line_number=idx,
                bundle_business_date=current_bundle_business_date,
                bundle_id=current_bundle_id,
                bundle_sequence_number=current_bundle_sequence_number,
                item_sequence_number=check_ctx.get("item_sequence_number", ""),
                check_number=check_ctx.get("check_number", ""),
            )
            current_item = {
                "item_type": "25",
                "start_line": idx,
                "check_ref": check_ctx,
                "image_50_count": 0,
                "image_52_count": 0,
            }
            rec25_total += 1
            if open_25_line is not None and not open_25_has_26:
                missing_26_after_25_count += 1
                add_missing_26_detail("25", idx, "missing_26_before_next_25")
                add_issue(
                    f"Record 25 at line {open_25_line} has no corresponding 26 before next 25"
                )
            open_25_line = idx
            open_25_has_26 = False
            open_25_context = {
                "line_25": idx,
                "bundle_business_date": current_bundle_business_date,
                "bundle_id": current_bundle_id,
                "bundle_sequence_number": current_bundle_sequence_number,
                "cash_letter_business_date": current_cash_letter_business_date,
                "cash_letter_id": current_cash_letter_id,
                **check_ctx,
            }
        elif rt == "26":
            rec26_total += 1
            if open_25_line is None:
                orphan_26_count += 1
                add_issue(f"Record 26 at line {idx} is not preceded by record 25")
            else:
                open_25_has_26 = True
        elif rt == "31":
            finalize_current_item(f"record 31 at line {idx}")
            check_ctx_31 = _extract_check_context_from_31(line)
            check_ctx_31["unique_check_id"] = build_unique_check_id(
                file_name=file_name,
                item_type="31",
                line_number=idx,
                bundle_business_date=current_bundle_business_date,
                bundle_id=current_bundle_id,
                bundle_sequence_number=current_bundle_sequence_number,
                item_sequence_number=check_ctx_31.get("item_sequence_number", ""),
                check_number=check_ctx_31.get("check_number", ""),
            )
            current_item = {
                "item_type": "31",
                "start_line": idx,
                "check_ref": check_ctx_31,
                "image_50_count": 0,
                "image_52_count": 0,
            }
            if open_25_line is not None and not open_25_has_26:
                missing_26_after_25_count += 1
                add_missing_26_detail("31", idx, "missing_26_before_record_31")
                add_issue(
                    f"Record 25 at line {open_25_line} has no corresponding 26 before record 31 at line {idx}"
                )
            open_25_line = None
            open_25_has_26 = False
            open_25_context = None
        elif rt in close_25_context:
            if open_25_line is not None and not open_25_has_26:
                missing_26_after_25_count += 1
                add_missing_26_detail(rt, idx, f"missing_26_before_record_{rt}")
                add_issue(
                    f"Record 25 at line {open_25_line} has no corresponding 26 before record {rt} at line {idx}"
                )
            open_25_line = None
            open_25_has_26 = False
            open_25_context = None

        if rt in {"10", "20", "61", "62", "70", "90", "99", "01"}:
            finalize_current_item(f"record {rt} at line {idx}")

        if rt == "50":
            if current_item is not None:
                current_item["image_50_count"] = int(current_item.get("image_50_count", 0)) + 1
        elif rt == "52":
            if current_item is not None:
                current_item["image_52_count"] = int(current_item.get("image_52_count", 0)) + 1

    if open_25_line is not None and not open_25_has_26:
        missing_26_after_25_count += 1
        add_missing_26_detail("EOF", len(records), "missing_26_before_end_of_file")
        add_issue(f"Record 25 at line {open_25_line} has no corresponding 26 before end of file")
    open_25_context = None
    finalize_current_item("end of file")

    presentment_mode = ("01" in collection_type_values) or record_type_counts["25"] > 0 or record_type_counts["26"] > 0
    return_mode = ("03" in collection_type_values) or return_records_present

    missing_presentment_types = []
    if presentment_mode:
        missing_presentment_types = [
            rt for rt in PRESENTMENT_REQUIRED_TYPES if record_type_counts.get(rt, 0) == 0
        ]
        if missing_presentment_types:
            add_issue(
                "Missing presentment required record types: " + ", ".join(missing_presentment_types)
            )

    missing_return_types = []
    if return_mode:
        missing_return_types = [rt for rt in RETURN_REQUIRED_TYPES if record_type_counts.get(rt, 0) == 0]
        if missing_return_types:
            add_issue("Missing return required record types: " + ", ".join(missing_return_types))

    if record_type_counts["25"] > 0 and "01" not in collection_type_values:
        add_issue("Presentment check records found but collection type indicator 01 is missing")
    if return_records_present and "03" not in collection_type_values:
        add_issue("Return check records found but collection type indicator 03 is missing")

    missing_required_record_types = sorted(set(missing_presentment_types + missing_return_types))

    if presentment_items_without_front_image > 0:
        add_issue(
            (
                f"Presentment items missing record 50 (no image): {presentment_items_without_front_image:,}"
                + (
                    "\nExamples: " + ", ".join(presentment_missing_front_examples)
                    if presentment_missing_front_examples
                    else ""
                )
            )
        )
    if return_items_without_front_image > 0:
        add_issue(
            (
                f"Return items missing record 50 (no image): {return_items_without_front_image:,}"
                + (
                    "\nExamples: " + ", ".join(return_missing_front_examples)
                    if return_missing_front_examples
                    else ""
                )
            )
        )
    if presentment_items_without_image_pair > 0:
        add_issue(
            (
                f"Presentment items with record 50 but missing record 52: {presentment_items_without_image_pair:,}"
                + (
                    "\nExamples: " + ", ".join(presentment_missing_pair_examples)
                    if presentment_missing_pair_examples
                    else ""
                )
            )
        )
    if return_items_without_image_pair > 0:
        add_issue(
            (
                f"Return items with record 50 but missing record 52: {return_items_without_image_pair:,}"
                + (
                    "\nExamples: " + ", ".join(return_missing_pair_examples)
                    if return_missing_pair_examples
                    else ""
                )
            )
        )

    if dropped_issue_count:
        issues.append(
            f"... plus {dropped_issue_count} additional issues omitted for brevity."
        )

    return {
        "file": file_name,
        "is_valid": (
            header_ok
            and orphan_26_count == 0
            and missing_26_after_25_count == 0
            and len(missing_required_record_types) == 0
            and critical_field_error_count == 0
            and presentment_items_without_front_image == 0
            and return_items_without_front_image == 0
        ),
        "header_ok": header_ok,
        "orphan_26_count": orphan_26_count,
        "missing_26_after_25_count": missing_26_after_25_count,
        "collection_type_values": sorted(collection_type_values),
        "presentment_mode": presentment_mode,
        "return_mode": return_mode,
        "return_records_present": return_records_present,
        "missing_presentment_types": missing_presentment_types,
        "missing_return_types": missing_return_types,
        "missing_required_record_types": missing_required_record_types,
        "critical_field_error_count": critical_field_error_count,
        "record_type_counts": record_type_counts,
        "record_25_count": rec25_total,
        "record_26_count": rec26_total,
        "missing_26_detail_count": len(missing_26_details),
        "missing_26_details": missing_26_details,
        "presentment_item_count": presentment_item_count,
        "presentment_items_without_image_pair": presentment_items_without_image_pair,
        "presentment_items_without_front_image": presentment_items_without_front_image,
        "presentment_items_non_tiff": presentment_items_non_tiff,
        "return_item_count": return_item_count,
        "return_items_without_image_pair": return_items_without_image_pair,
        "return_items_without_front_image": return_items_without_front_image,
        "return_items_non_tiff": return_items_non_tiff,
        "issues": issues,
    }


def x9_to_json(filename):
    """Convert X9 format file to JSON rows."""
    forward_rows = []
    return_rows = []
    json_result = {"filename": os.path.basename(filename)}
    encoding = "ascii"

    with open(filename, "rb") as file:
        detected = chardet.detect(file.read(50)).get("encoding")
        if detected and detected.lower() != "ascii":
            encoding = "cp500"

    with codecs.open(filename, "r", encoding=encoding, errors="ignore") as file:
        lines = [line for line in file.read().split("\x00") if line]

        if len(lines) < 3:
            print(f"Warning: File {filename} has less than 3 records")
            return forward_rows, return_rows

        record_type_01 = get_record_type_values(lines[0])
        record_type_10 = get_record_type_values(lines[1])
        record_type_20 = get_record_type_values(lines[2])

        current_index = 3
        line = lines[current_index] if current_index < len(lines) else None

        while current_index < len(lines) and line:
            record = get_record_type_values(line)

            if get_record_type(line) == "25":
                record_type_25 = record
                current_index += 1
                line = lines[current_index] if current_index < len(lines) else None
                addendum = {}

                while (
                    line
                    and get_record_type(line) not in {"25", "31"}
                    and current_index < len(lines)
                ):
                    if get_record_type(line) in ("26", "28"):
                        values = get_record_type_values(lines[current_index])
                        for key, value in values.items():
                            addendum.setdefault(key, []).append(value)
                    current_index += 1
                    line = lines[current_index] if current_index < len(lines) else None

                for key, value in addendum.items():
                    addendum[key] = "|".join(value)

                forward_rows.append(
                    {
                        **json_result,
                        **record_type_01,
                        **record_type_10,
                        **record_type_20,
                        **record_type_25,
                        **addendum,
                    }
                )

            elif get_record_type(line) == "31":
                record_type_31 = record
                current_index += 1
                line = lines[current_index] if current_index < len(lines) else None
                addendum = {}

                while (
                    line
                    and get_record_type(line) not in {"25", "31"}
                    and current_index < len(lines)
                ):
                    if get_record_type(line) in ("32", "33", "35"):
                        values = get_record_type_values(lines[current_index])
                        for key, value in values.items():
                            addendum.setdefault(key, []).append(value)
                    current_index += 1
                    line = lines[current_index] if current_index < len(lines) else None

                for key, value in addendum.items():
                    addendum[key] = "|".join(value)

                return_rows.append(
                    {
                        **json_result,
                        **record_type_01,
                        **record_type_10,
                        **record_type_20,
                        **record_type_31,
                        **addendum,
                    }
                )
            else:
                current_index += 1
                line = lines[current_index] if current_index < len(lines) else None

    return forward_rows, return_rows


def classify_transaction(row, our_aba_list):
    """Classify into three direction buckets using payor/BOFD ABA membership."""
    try:
        payor = _normalize_scalar_text(row.get("25_payor_bank_routing_number", "")) + _normalize_scalar_text(
            row.get("25_payor_bank_routing_number_check_digit", "")
        )
        bofd = _normalize_scalar_text(row.get("26_bofd_routing_number", ""))
        payor_is_ours = payor in our_aba_list
        bofd_is_ours = bofd in our_aba_list
        if payor_is_ours and bofd_is_ours:
            return "ON_US"
        if bofd_is_ours:
            return "DEPOSIT"
        # Customer-requested direction model has only three buckets:
        # DEPOSIT / ON_US / WITHDRAWAL. Both-external items are grouped as WITHDRAWAL.
        return "WITHDRAWAL"
    except Exception:
        return "UNKNOWN"


def credit_debit_flag(row, our_aba_list):
    """Determine credit/debit flag based on routing numbers."""
    try:
        bofd = _normalize_scalar_text(row.get("BOFD_ROUTING"))
        payor = _normalize_scalar_text(row.get("PAYOR_ROUTING"))
        if bofd in our_aba_list:
            return "CREDIT"
        if payor in our_aba_list:
            return "DEBIT"
        return "EXTERNAL"
    except Exception:
        return "UNKNOWN"


def top_10(df):
    """Get top 10 transactions including check number and amount."""
    if df.empty:
        return pd.DataFrame()

    cols = ["payer_account", "check_number", "PAYOR_ROUTING", "BOFD_ROUTING", "ITEM_AMOUNT_FLOAT"]
    missing_cols = [c for c in cols if c not in df.columns]
    if missing_cols:
        return pd.DataFrame()

    top_df = (
        df.groupby(cols, dropna=False)
        .size()
        .reset_index(name="COUNT")
        .sort_values("COUNT", ascending=False)
        .head(10)
    )
    top_df["ITEM_AMOUNT_FLOAT"] = pd.to_numeric(top_df["ITEM_AMOUNT_FLOAT"], errors="coerce")
    top_df["ITEM_AMOUNT"] = top_df["ITEM_AMOUNT_FLOAT"].apply(
        lambda x: f"${x:.2f}" if pd.notna(x) else ""
    )
    top_df.drop(columns=["ITEM_AMOUNT_FLOAT"], inplace=True)
    return top_df


def run_phase2_field_level_checks(df_forward: pd.DataFrame, df_return: pd.DataFrame):
    """
    Phase 2 - Field-Level Validation by Record Type.
    Returns list of log_check payload tuples: (check_name, status, details, guideline).
    Supports presentment (25/26) and return (31/32) checks.
    """
    results = []

    # Presentment (25/26)
    if not df_forward.empty:
        total = len(df_forward)
        required_cols = [
            "25_auxiliary_on_us",
            "25_payor_bank_routing_number",
            "25_payor_bank_routing_number_check_digit",
            "25_on_us",
            "26_bofd_routing_number",
            "26_bofd_business_date",
            "26_bofd_item_sequence_number",
            "26_deposit_account_number_at_bofd",
            "TRANSACTION_TYPE",
            "26_payee_name",
        ]
        for col in required_cols:
            if col not in df_forward.columns:
                df_forward[col] = ""

        rt25_aux_series = _normalize_text_series(df_forward, "25_auxiliary_on_us")
        rt25_payor_rt_series = _normalize_text_series(df_forward, "25_payor_bank_routing_number")
        rt25_payor_cd_series = _normalize_text_series(df_forward, "25_payor_bank_routing_number_check_digit")
        rt25_onus_series = _normalize_text_series(df_forward, "25_on_us")

        rt25_aux_missing = (rt25_aux_series == "").sum()
        rt25_payor_rt_missing = (~rt25_payor_rt_series.str.fullmatch(r"\d{8}")).sum()
        rt25_payor_cd_missing = (~rt25_payor_cd_series.str.fullmatch(r"\d")).sum()
        rt25_onus_missing = (rt25_onus_series == "").sum()
        rt25_micr_missing = ((rt25_onus_series == "") & (rt25_aux_series == "")).sum()

        rt25_failed = any(
            [
                rt25_aux_missing > 0,
                rt25_payor_rt_missing > 0,
                rt25_payor_cd_missing > 0,
                rt25_onus_missing > 0,
                rt25_micr_missing > 0,
            ]
        )
        rt25_status = "FAIL" if rt25_failed else "PASS"
        rt25_details = (
            f"Total RT25 records: {total:,}\n"
            f"Missing AUX ON_US: {rt25_aux_missing:,}\n"
            f"Invalid/Missing Payor Bank RT (8 digits): {rt25_payor_rt_missing:,}\n"
            f"Invalid/Missing Payor Bank Check Digit: {rt25_payor_cd_missing:,}\n"
            f"Missing ON_US: {rt25_onus_missing:,}\n"
            f"Missing MICR (AUX+ON_US both empty): {rt25_micr_missing:,}"
        )
        results.append(
            (
                "Phase 2 - RT25 Mandatory Fields",
                rt25_status,
                rt25_details,
                "RT25 must include AUX ON_US, payor RT/check digit, ON_US, and MICR data.",
            )
        )

        rt26_bofd_rt_series = _normalize_text_series(df_forward, "26_bofd_routing_number")
        rt26_bofd_date_series = _normalize_text_series(df_forward, "26_bofd_business_date")
        rt26_bofd_item_seq_series = _normalize_text_series(df_forward, "26_bofd_item_sequence_number")
        rt26_deposit_account_series = _normalize_text_series(df_forward, "26_deposit_account_number_at_bofd")

        rt26_bofd_rt_missing = (~rt26_bofd_rt_series.str.fullmatch(r"\d{9}")).sum()
        rt26_bofd_business_date_missing = (~rt26_bofd_date_series.str.fullmatch(r"\d{8}")).sum()
        rt26_bofd_item_seq_missing = (rt26_bofd_item_seq_series == "").sum()
        rt26_deposit_account_missing = (rt26_deposit_account_series == "").sum()

        is_deposit = df_forward["TRANSACTION_TYPE"] == "DEPOSIT"
        is_withdrawal = df_forward["TRANSACTION_TYPE"] == "WITHDRAWAL"
        dep_total = int(is_deposit.sum())
        wdr_total = int(is_withdrawal.sum())
        rt26_deposit_account_missing_for_deposits = (rt26_deposit_account_series[is_deposit] == "").sum()
        rt26_deposit_account_missing_for_withdrawals = (rt26_deposit_account_series[is_withdrawal] == "").sum()

        rt26_failed = any(
            [
                rt26_bofd_rt_missing > 0,
                rt26_bofd_business_date_missing > 0,
                rt26_bofd_item_seq_missing > 0,
                rt26_deposit_account_missing_for_deposits > 0,
            ]
        )
        rt26_status = "FAIL" if rt26_failed else "PASS"
        rt26_details = (
            f"Total RT26-linked records: {total:,}\n"
            f"Invalid/Missing BOFD RT (9 digits): {rt26_bofd_rt_missing:,}\n"
            f"Invalid/Missing BOFD Business Endorsement Date (YYYYMMDD): {rt26_bofd_business_date_missing:,}\n"
            f"Missing BOFD Sequence Number: {rt26_bofd_item_seq_missing:,}\n"
            f"Missing Deposit Account Number (all txns): {rt26_deposit_account_missing:,}\n"
            f"Deposits: {dep_total:,}, missing deposit account (mandatory): {rt26_deposit_account_missing_for_deposits:,}\n"
            f"Withdrawals: {wdr_total:,}, missing deposit account (optional): {rt26_deposit_account_missing_for_withdrawals:,}"
        )
        results.append(
            (
                "Phase 2 - RT26 Mandatory Fields",
                rt26_status,
                rt26_details,
                "RT26 must include BOFD RT, business date, BOFD sequence. Deposit account is mandatory for deposits and optional for withdrawals.",
            )
        )

        rt26_payee_populated = (_normalize_text_series(df_forward, "26_payee_name") != "").sum()
        results.append(
            (
                "Phase 2 - RT26 Optional Fields",
                "INFO",
                (
                    f"RT26 Payee Name populated: {rt26_payee_populated:,}/{total:,}\n"
                    "User Field: not present in current parser (future feature)."
                ),
                "Optional fields are informational and do not fail validation.",
            )
        )
    else:
        results.append(
            (
                "Phase 2 - Presentment Field Validation Availability",
                "INFO",
                "No RT25/RT26 presentment records available. Presentment field checks skipped.",
                "This is expected for return-only datasets.",
            )
        )

    # Returns (31/32)
    if not df_return.empty:
        rtotal = len(df_return)
        return_required_cols = [
            "31_payor_bank_routing_number",
            "31_payor_bank_routing_number_check_digit",
            "31_on_us_return_record",
            "31_item_amount",
            "32_bofd_routing_number",
            "32_bofd_business_date",
            "32_bofd_item_sequence_number",
            "32_deposit_account_number_at_bofd",
        ]
        for col in return_required_cols:
            if col not in df_return.columns:
                df_return[col] = ""

        rt31_payor_rt_series = _normalize_text_series(df_return, "31_payor_bank_routing_number")
        rt31_payor_cd_series = _normalize_text_series(df_return, "31_payor_bank_routing_number_check_digit")
        rt31_onus_series = _normalize_text_series(df_return, "31_on_us_return_record")
        rt31_amount_series = _normalize_text_series(df_return, "31_item_amount")

        rt31_payor_rt_missing = (~rt31_payor_rt_series.str.fullmatch(r"\d{8}")).sum()
        rt31_payor_cd_missing = (~rt31_payor_cd_series.str.fullmatch(r"\d")).sum()
        rt31_onus_missing = (rt31_onus_series == "").sum()
        rt31_amount_missing = (~rt31_amount_series.str.fullmatch(r"\d+")).sum()

        rt31_failed = any(
            [
                rt31_payor_rt_missing > 0,
                rt31_payor_cd_missing > 0,
                rt31_onus_missing > 0,
                rt31_amount_missing > 0,
            ]
        )
        rt31_status = "FAIL" if rt31_failed else "PASS"
        rt31_details = (
            f"Total RT31 records: {rtotal:,}\n"
            f"Invalid/Missing Payor Bank RT (8 digits): {rt31_payor_rt_missing:,}\n"
            f"Invalid/Missing Payor Bank Check Digit: {rt31_payor_cd_missing:,}\n"
            f"Missing ON_US Return Record: {rt31_onus_missing:,}\n"
            f"Missing/Invalid Return Item Amount: {rt31_amount_missing:,}"
        )
        results.append(
            (
                "Phase 2 - RT31 Mandatory Fields",
                rt31_status,
                rt31_details,
                "RT31 must include payor RT/check digit, ON_US return record, and item amount.",
            )
        )

        rt32_bofd_rt_series = _normalize_text_series(df_return, "32_bofd_routing_number")
        rt32_bofd_date_series = _normalize_text_series(df_return, "32_bofd_business_date")
        rt32_bofd_seq_series = _normalize_text_series(df_return, "32_bofd_item_sequence_number")
        rt32_deposit_account_series = _normalize_text_series(df_return, "32_deposit_account_number_at_bofd")

        rt32_bofd_rt_missing = (~rt32_bofd_rt_series.str.fullmatch(r"\d{9}")).sum()
        rt32_bofd_date_missing = (~rt32_bofd_date_series.str.fullmatch(r"\d{8}")).sum()
        rt32_bofd_seq_missing = (rt32_bofd_seq_series == "").sum()
        rt32_deposit_account_missing = (rt32_deposit_account_series == "").sum()

        rt32_failed = any(
            [
                rt32_bofd_rt_missing > 0,
                rt32_bofd_date_missing > 0,
                rt32_bofd_seq_missing > 0,
                rt32_deposit_account_missing > 0,
            ]
        )
        rt32_status = "FAIL" if rt32_failed else "PASS"
        rt32_details = (
            f"Total RT32-linked records: {rtotal:,}\n"
            f"Invalid/Missing BOFD RT (9 digits): {rt32_bofd_rt_missing:,}\n"
            f"Invalid/Missing BOFD Business Date: {rt32_bofd_date_missing:,}\n"
            f"Missing BOFD Item Sequence Number: {rt32_bofd_seq_missing:,}\n"
            f"Missing Deposit Account Number at BOFD: {rt32_deposit_account_missing:,}"
        )
        results.append(
            (
                "Phase 2 - RT32 Mandatory Fields",
                rt32_status,
                rt32_details,
                "RT32 must include BOFD RT, business date, BOFD sequence, and deposit account number.",
            )
        )

        issues_31 = df_return[
            ~(
                rt31_payor_rt_series.str.fullmatch(r"\d{8}")
                & rt31_payor_cd_series.str.fullmatch(r"\d")
                & (rt31_onus_series != "")
                & rt31_amount_series.str.fullmatch(r"\d+")
            )
        ].copy()
        issues_32 = df_return[
            ~(
                rt32_bofd_rt_series.str.fullmatch(r"\d{9}")
                & rt32_bofd_date_series.str.fullmatch(r"\d{8}")
                & (rt32_bofd_seq_series != "")
                & (rt32_deposit_account_series != "")
            )
        ].copy()
        return_field_issues = pd.concat([issues_31, issues_32], ignore_index=True).drop_duplicates()
        if not return_field_issues.empty:
            top_files = return_field_issues["filename"].value_counts().head(10).reset_index()
            top_files.columns = ["filename", "issue_count"]
            results.append(
                (
                    "Phase 2 - Return Field Issue Files (Top 10)",
                    "INFO",
                    f"\n{top_files.to_string(index=False)}",
                    "Use return_result TSV for row-level investigation by filename.",
                )
            )
    else:
        results.append(
            (
                "Phase 2 - Return Field Validation Availability",
                "INFO",
                "No RT31/RT32 return records available. Return field checks skipped.",
                "Return records are optional and may be delivered in separate files.",
            )
        )

    return results


def weekdays_between_dates(start_date, end_date):
    """Get list of weekdays between two dates."""
    weekdays = []
    current_date = start_date
    while current_date <= end_date:
        if current_date.weekday() < 5:
            weekdays.append(current_date)
        current_date += timedelta(days=1)
    return weekdays


def extract_valid_yyyymmdd_tokens(text: str) -> List[str]:
    """Return valid standalone YYYYMMDD tokens found in text."""
    tokens = re.findall(r"(?<!\d)\d{8}(?!\d)", text or "")
    valid_tokens = []
    for token in tokens:
        try:
            datetime.strptime(token, "%Y%m%d")
            valid_tokens.append(token)
        except ValueError:
            continue
    return valid_tokens


def read_x937_file(file_path):
    """Read X937 file with encoding detection and split by NUL record separator."""
    encoding = "ascii"
    with open(file_path, "rb") as f:
        detected = chardet.detect(f.read(50)).get("encoding")
        if detected and detected.lower() != "ascii":
            encoding = "cp500"
    with codecs.open(file_path, "r", encoding=encoding, errors="ignore") as f:
        content = f.read()
    return [line for line in content.split("\x00") if line.strip()]


def parse_x937_record(line: str):
    """Syntax-only X9.37 validation. Raises exception if record is structurally invalid."""
    if not line or len(line) < 3:
        raise ValueError("Empty or too short record")
    record_type = get_record_type(line)
    if record_type not in X937_VALID_RECORD_TYPES:
        raise ValueError(f"Unknown record type: {record_type}")
    if record_type in X9_FIELDS:
        max_end = max(v[1] for v in X9_FIELDS[record_type].values())
        if len(line) < max_end:
            raise ValueError(f"Record too short for type {record_type}: {len(line)} < {max_end}")
    return True


def load_jsonl_df(jsonl_path):
    """Load JSONL file into DataFrame safely."""
    if not os.path.exists(jsonl_path) or os.path.getsize(jsonl_path) == 0:
        return pd.DataFrame()
    return pd.read_json(jsonl_path, encoding="latin-1", lines=True)


def compact_issue_text(issues: List[str], max_items: int = 12, max_chars: int = 2400) -> str:
    """Build compact issue preview text for TSV output."""
    if not issues:
        return "No detailed issues."
    shown = issues[:max_items]
    preview = " | ".join(shown)
    remaining = len(issues) - len(shown)
    if remaining > 0:
        preview += f" | ... ({remaining} more issues)"
    if len(preview) > max_chars:
        preview = preview[: max_chars - 3] + "..."
    return preview


def _extract_check_context_from_31(line: str) -> Dict[str, str]:
    """Extract check-identifying fields from record 31 for pinpoint/reporting."""
    on_us_return = _slice(line, 12, 32)
    seq = _slice(line, 54, 69)
    on_us_clean = on_us_return.strip("/")
    on_us_parts = [p for p in on_us_clean.split("/") if p]
    payer_account = on_us_parts[0] if on_us_parts else ""
    check_number = on_us_parts[-1] if on_us_parts else ""
    return {
        "payer_account": payer_account,
        "check_number": check_number,
        "on_us": on_us_return,
        "aux_on_us": "",
        "item_sequence_number": seq,
    }


def build_unique_check_id(
    file_name: str,
    item_type: str,
    line_number: int,
    bundle_business_date: str = "",
    bundle_id: str = "",
    bundle_sequence_number: str = "",
    item_sequence_number: str = "",
    check_number: str = "",
) -> str:
    """Build stable per-item unique identifier for customer-facing reports."""
    parts = [
        os.path.basename(file_name or ""),
        item_type or "",
        bundle_business_date or "",
        bundle_id or "",
        bundle_sequence_number or "",
        item_sequence_number or "",
        check_number or "",
        str(line_number),
    ]
    return "|".join(parts)


def build_unique_check_components(
    file_name: str,
    item_type: str,
    bundle_business_date: str = "",
    bundle_id: str = "",
    bundle_sequence_number: str = "",
    item_sequence_number: str = "",
    check_number: str = "",
    line_number: int = 0,
) -> Dict[str, Any]:
    """Return explicit unique-check key fields for UI/JSON consumption."""
    return {
        "filename": os.path.basename(file_name or ""),
        "item_type": item_type or "",
        "bundle_business_date": bundle_business_date or "",
        "bundle_id": bundle_id or "",
        "bundle_sequence_number": bundle_sequence_number or "",
        "item_sequence_number": item_sequence_number or "",
        "check_number": check_number or "",
        "line_number": int(line_number or 0),
    }


def _record_fields_for_ui(line: str) -> Dict[str, Any]:
    """Convert one X9 line into compact, UI-friendly field payload."""
    rt = get_record_type(line)
    if rt in {"50", "52", "54"}:
        if rt == "50":
            return {
                "line_length": len(line),
                "has_image_metadata": bool(_slice(line, 3)),
            }
        if rt == "52":
            return {
                "line_length": len(line),
                "has_image_data": bool(_slice(line, 3)),
            }
        return {
            "line_length": len(line),
            "has_analysis_data": bool(_slice(line, 3)),
        }

    if rt in X9_FIELDS:
        values = get_record_type_values(line)
        prefix = f"{rt}_"
        compact = {}
        for key, value in values.items():
            short_key = key[len(prefix) :] if key.startswith(prefix) else key
            compact[short_key] = value.strip()
        return compact

    return {"line_length": len(line)}


def _record_node_for_ui(line: str, line_number: int) -> Dict[str, Any]:
    """Build a compact record node with line number, type, and normalized fields."""
    return {
        "line": line_number,
        "record_type": get_record_type(line),
        "fields": _record_fields_for_ui(line),
    }


def build_hierarchical_file_report(
    file_name: str, records: List[str], structure: Dict[str, Any], syntax_errors: int
) -> Dict[str, Any]:
    """
    Build hierarchical JSON for UI:
    file -> cash_letters -> bundles -> items (25/31) -> addenda/images.
    """
    report: Dict[str, Any] = {
        "filename": file_name,
        "is_valid": structure.get("is_valid", False) and syntax_errors == 0,
        "syntax_errors": syntax_errors,
        "structure_summary": {
            "header_ok": structure.get("header_ok", False),
            "orphan_26_count": structure.get("orphan_26_count", 0),
            "missing_26_after_25_count": structure.get("missing_26_after_25_count", 0),
            "critical_field_error_count": structure.get("critical_field_error_count", 0),
            "missing_required_record_types": structure.get("missing_required_record_types", []),
        },
        "collection_type_values": structure.get("collection_type_values", []),
        "issues": structure.get("issues", []),
        "missing_26_details": structure.get("missing_26_details", []),
        "file_header_01": None,
        "cash_letters": [],
        "orphan_records": [],
        "ignored_non_x9_fragments": 0,
    }

    current_cash_letter = None
    current_bundle = None
    current_item = None

    def ensure_cash_letter():
        nonlocal current_cash_letter
        if current_cash_letter is None:
            current_cash_letter = {
                "header_10": None,
                "bundles": [],
                "orphan_records": [],
            }
            report["cash_letters"].append(current_cash_letter)
        return current_cash_letter

    def ensure_bundle():
        nonlocal current_bundle
        cl = ensure_cash_letter()
        if current_bundle is None:
            current_bundle = {
                "header_20": None,
                "presentment_items": [],
                "return_items": [],
                "trailer_records": [],
                "orphan_records": [],
            }
            cl["bundles"].append(current_bundle)
        return current_bundle

    def finalize_item():
        nonlocal current_item
        if current_item is None:
            return

        bundle = ensure_bundle()
        if current_item["item_record_type"] == "25":
            bundle["presentment_items"].append(current_item)
        else:
            bundle["return_items"].append(current_item)
        current_item = None

    for idx, line in enumerate(records, start=1):
        rt = get_record_type(line)
        if rt not in X937_VALID_RECORD_TYPES:
            report["ignored_non_x9_fragments"] += 1
            continue
        node = _record_node_for_ui(line, idx)

        if rt == "01":
            report["file_header_01"] = node
            continue

        if rt == "10":
            finalize_item()
            current_bundle = None
            current_cash_letter = {
                "header_10": node,
                "bundles": [],
                "orphan_records": [],
            }
            report["cash_letters"].append(current_cash_letter)
            continue

        if rt == "20":
            finalize_item()
            cl = ensure_cash_letter()
            current_bundle = {
                "header_20": node,
                "presentment_items": [],
                "return_items": [],
                "trailer_records": [],
                "orphan_records": [],
            }
            cl["bundles"].append(current_bundle)
            continue

        if rt == "25":
            finalize_item()
            check_ctx = _extract_check_context_from_25(line)
            bundle_business_date = ""
            bundle_id = ""
            bundle_sequence_number = ""
            if current_bundle and current_bundle.get("header_20"):
                h20 = current_bundle["header_20"]["fields"]
                bundle_business_date = str(h20.get("bundle_business_date", ""))
                bundle_id = str(h20.get("bundle_id", ""))
                bundle_sequence_number = str(h20.get("bundle_sequence_number", ""))
            unique_components = build_unique_check_components(
                file_name=file_name,
                item_type="25",
                bundle_business_date=bundle_business_date,
                bundle_id=bundle_id,
                bundle_sequence_number=bundle_sequence_number,
                item_sequence_number=check_ctx.get("item_sequence_number", ""),
                check_number=check_ctx.get("check_number", ""),
                line_number=idx,
            )
            check_ctx["unique_check_id"] = build_unique_check_id(
                file_name=file_name,
                item_type="25",
                line_number=idx,
                bundle_business_date=bundle_business_date,
                bundle_id=bundle_id,
                bundle_sequence_number=bundle_sequence_number,
                item_sequence_number=check_ctx.get("item_sequence_number", ""),
                check_number=check_ctx.get("check_number", ""),
            )
            check_ctx["unique_check_components"] = unique_components
            current_item = {
                "item_record_type": "25",
                "unique_check_id": check_ctx["unique_check_id"],
                "unique_check_components": unique_components,
                "record_25": node,
                "check_context": check_ctx,
                "addenda": [],
                "images": {
                    "records_50": [],
                    "records_52": [],
                    "records_54": [],
                },
            }
            ensure_bundle()
            continue

        if rt == "31":
            finalize_item()
            check_ctx_31 = _extract_check_context_from_31(line)
            bundle_business_date = ""
            bundle_id = ""
            bundle_sequence_number = ""
            if current_bundle and current_bundle.get("header_20"):
                h20 = current_bundle["header_20"]["fields"]
                bundle_business_date = str(h20.get("bundle_business_date", ""))
                bundle_id = str(h20.get("bundle_id", ""))
                bundle_sequence_number = str(h20.get("bundle_sequence_number", ""))
            unique_components = build_unique_check_components(
                file_name=file_name,
                item_type="31",
                bundle_business_date=bundle_business_date,
                bundle_id=bundle_id,
                bundle_sequence_number=bundle_sequence_number,
                item_sequence_number=check_ctx_31.get("item_sequence_number", ""),
                check_number=check_ctx_31.get("check_number", ""),
                line_number=idx,
            )
            check_ctx_31["unique_check_id"] = build_unique_check_id(
                file_name=file_name,
                item_type="31",
                line_number=idx,
                bundle_business_date=bundle_business_date,
                bundle_id=bundle_id,
                bundle_sequence_number=bundle_sequence_number,
                item_sequence_number=check_ctx_31.get("item_sequence_number", ""),
                check_number=check_ctx_31.get("check_number", ""),
            )
            check_ctx_31["unique_check_components"] = unique_components
            current_item = {
                "item_record_type": "31",
                "unique_check_id": check_ctx_31["unique_check_id"],
                "unique_check_components": unique_components,
                "record_31": node,
                "check_context": check_ctx_31,
                "addenda": [],
                "images": {
                    "records_50": [],
                    "records_52": [],
                    "records_54": [],
                },
            }
            ensure_bundle()
            continue

        # Item-level addenda/images
        if current_item is not None:
            if current_item["item_record_type"] == "25" and rt in {"26", "28"}:
                current_item["addenda"].append(node)
                continue
            if current_item["item_record_type"] == "31" and rt in {"32", "33", "35"}:
                current_item["addenda"].append(node)
                continue
            if rt == "50":
                current_item["images"]["records_50"].append(node)
                continue
            if rt == "52":
                current_item["images"]["records_52"].append(node)
                continue
            if rt == "54":
                current_item["images"]["records_54"].append(node)
                continue

        # Bundle-level trailers / unscoped records.
        if rt in {"50", "52", "54"}:
            ensure_bundle()["orphan_records"].append(node)
        elif rt in {"61", "62", "70", "90", "99"}:
            ensure_bundle()["trailer_records"].append(node)
        elif rt in {"26", "28", "32", "33", "35"}:
            ensure_bundle()["orphan_records"].append(node)
        else:
            report["orphan_records"].append(node)

    finalize_item()
    return report


def process_x9_files(x937_dir, sample_days, our_aba, config):
    """Main processing function for X9 files."""
    current_time = datetime.now().strftime("%Y%m%d")

    our_aba_list = [aba.strip() for aba in our_aba.split(",") if aba.strip()]

    try:
        bad_record_threshold = config.getfloat("VALIDATION", "bad_record_threshold")
        allow_zero = config.getboolean("VALIDATION", "allow_zero_amount")
        allow_missing = config.getboolean("VALIDATION", "allow_missing_amount")
        onus_max = config.getint("VALIDATION", "onus_max_elements")
        enable_outlier_detection = config.getboolean("VALIDATION", "enable_outlier_detection")
        iqr_multiplier = config.getfloat("VALIDATION", "iqr_multiplier")
        enable_duplicate_check = config.getboolean("VALIDATION", "enable_duplicate_check")
        enable_sequence_check = config.getboolean("VALIDATION", "enable_sequence_check")
        enable_date_continuity = config.getboolean("VALIDATION", "enable_date_continuity")
    except Exception:
        bad_record_threshold = 5.0
        allow_zero, allow_missing, onus_max = False, False, 3
        enable_outlier_detection, iqr_multiplier = True, 3.0
        enable_duplicate_check, enable_sequence_check = True, True
        enable_date_continuity = True

    x9_files = [p for p in glob.glob(f"{x937_dir}/*") if os.path.isfile(p)]
    if not x9_files:
        print(f"ERROR: No files found in {x937_dir}")
        return

    if sample_days > 0:
        file_date_map = {}
        for path in x9_files:
            base = os.path.basename(path)
            tokens = extract_valid_yyyymmdd_tokens(base)
            if tokens:
                file_date_map[path] = tokens[0]
        dates = sorted(set(file_date_map.values()))
        if dates:
            sample_dates = dates[:sample_days]
            x9_files = [f for f in x9_files if file_date_map.get(f) in sample_dates]
            print(f"Sampling: {sample_days} days\n")

    file_count = len(x9_files)
    if file_count == 0:
        print("ERROR: No files to process")
        return

    print(f"Configuration: OUR_ABA_LIST={our_aba_list}, Files={file_count}\n")
    log_section_start("SECTION 1 X937 RDV VALIDATION TEST")

    # ============================================================
    # PRE-SCAN: syntax and structure validation per file
    # ============================================================
    valid_x9_files = []
    invalid_file_rows = []
    structure_results = []
    hierarchical_reports = []
    total_record_cnt = 0
    bad_record_cnt = 0

    for path in x9_files:
        syntax_errors = 0
        records = []
        try:
            records = read_x937_file(path)
            for line in records:
                total_record_cnt += 1
                try:
                    parse_x937_record(line)
                except Exception:
                    syntax_errors += 1
                    bad_record_cnt += 1
        except Exception as e:
            unreadable_structure = {
                "file": os.path.basename(path),
                "is_valid": False,
                "header_ok": False,
                "orphan_26_count": 0,
                "missing_26_after_25_count": 0,
                "critical_field_error_count": 0,
                "missing_required_record_types": list(PRESENTMENT_REQUIRED_TYPES),
                "collection_type_values": [],
                "issues": [f"Unable to read file: {e}"],
                "missing_26_details": [],
            }
            hierarchical_reports.append(
                build_hierarchical_file_report(
                    file_name=os.path.basename(path),
                    records=[],
                    structure=unreadable_structure,
                    syntax_errors=0,
                )
            )
            invalid_file_rows.append(
                {
                    "filename": os.path.basename(path),
                    "status": "INVALID",
                    "header_ok": False,
                    "orphan_26_count": 0,
                    "missing_26_after_25_count": 0,
                    "missing_26_detail_count": 0,
                    "collection_type_values": "",
                    "missing_presentment_types": ",".join(PRESENTMENT_REQUIRED_TYPES),
                    "missing_return_types": ",".join(RETURN_REQUIRED_TYPES),
                    "missing_required_record_types": ",".join(PRESENTMENT_REQUIRED_TYPES),
                    "critical_field_error_count": 0,
                    "presentment_items_without_image_pair": 0,
                    "presentment_items_without_front_image": 0,
                    "presentment_items_non_tiff": 0,
                    "return_items_without_image_pair": 0,
                    "return_items_without_front_image": 0,
                    "return_items_non_tiff": 0,
                    "syntax_errors": 0,
                    "issue_count": 1,
                    "issues_preview": f"Unable to read file: {e}",
                }
            )
            continue

        structure = validate_x937_file_structure(records, os.path.basename(path))
        structure_results.append(structure)
        hierarchical_reports.append(
            build_hierarchical_file_report(
                file_name=os.path.basename(path),
                records=records,
                structure=structure,
                syntax_errors=syntax_errors,
            )
        )
        has_structure_errors = not structure["is_valid"]
        if syntax_errors == 0 and not has_structure_errors:
            valid_x9_files.append(path)
        else:
            issues = list(structure["issues"])
            invalid_file_rows.append(
                {
                    "filename": os.path.basename(path),
                    "status": "INVALID",
                    "header_ok": structure["header_ok"],
                    "orphan_26_count": structure["orphan_26_count"],
                    "missing_26_after_25_count": structure["missing_26_after_25_count"],
                    "missing_26_detail_count": structure["missing_26_detail_count"],
                    "collection_type_values": ",".join(structure["collection_type_values"]),
                    "missing_presentment_types": ",".join(structure["missing_presentment_types"]),
                    "missing_return_types": ",".join(structure["missing_return_types"]),
                    "missing_required_record_types": ",".join(structure["missing_required_record_types"]),
                    "critical_field_error_count": structure["critical_field_error_count"],
                    "presentment_items_without_image_pair": structure["presentment_items_without_image_pair"],
                    "presentment_items_without_front_image": structure["presentment_items_without_front_image"],
                    "presentment_items_non_tiff": structure["presentment_items_non_tiff"],
                    "return_items_without_image_pair": structure["return_items_without_image_pair"],
                    "return_items_without_front_image": structure["return_items_without_front_image"],
                    "return_items_non_tiff": structure["return_items_non_tiff"],
                    "syntax_errors": syntax_errors,
                    "issue_count": len(issues) + (1 if syntax_errors > 0 else 0),
                    "issues_preview": compact_issue_text(issues),
                }
            )

    invalid_structure_report = None
    missing_26_detail_report = None
    if invalid_file_rows:
        invalid_structure_report = f"invalid_x937_structure_{current_time}.tsv"
        report_columns = [
            "filename",
            "status",
            "header_ok",
            "collection_type_values",
            "missing_presentment_types",
            "missing_return_types",
            "missing_required_record_types",
            "orphan_26_count",
            "missing_26_after_25_count",
            "missing_26_detail_count",
            "critical_field_error_count",
            "presentment_items_without_image_pair",
            "presentment_items_without_front_image",
            "presentment_items_non_tiff",
            "return_items_without_image_pair",
            "return_items_without_front_image",
            "return_items_non_tiff",
            "syntax_errors",
            "issue_count",
            "issues_preview",
        ]
        pd.DataFrame(invalid_file_rows)[report_columns].to_csv(
            invalid_structure_report,
            sep="\t",
            index=False,
        )

    missing_26_rows = []
    for result in structure_results:
        missing_26_rows.extend(result.get("missing_26_details", []))
    if missing_26_rows:
        missing_26_detail_report = f"missing_26_detail_{current_time}.tsv"
        missing_26_columns = [
            "filename",
            "unique_check_id",
            "line_25",
            "bundle_business_date",
            "bundle_id",
            "bundle_sequence_number",
            "cash_letter_business_date",
            "cash_letter_id",
            "check_number",
            "payer_account",
            "on_us",
            "aux_on_us",
            "item_sequence_number",
            "boundary_record_type",
            "boundary_line",
            "reason",
        ]
        pd.DataFrame(missing_26_rows)[missing_26_columns].to_csv(
            missing_26_detail_report,
            sep="\t",
            index=False,
        )

    hierarchical_report_path = f"x937_hierarchical_report_{current_time}.json"
    with open(hierarchical_report_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "files_scanned": file_count,
                "files_valid_for_processing": len(valid_x9_files),
                "files_invalid": len(invalid_file_rows),
                "files": hierarchical_reports,
            },
            f,
            indent=2,
        )

    # Convert only valid files
    forward_json_file = f"fw_check_validation_{current_time}.jsonl"
    return_json_file = f"ret_check_validation_{current_time}.jsonl"

    print(f"Converting X9 files (valid files: {len(valid_x9_files):,}/{file_count:,})...")
    with open(forward_json_file, "w") as fw_file, open(return_json_file, "w") as ret_file:
        for x9_file in valid_x9_files:
            try:
                forward_rows, return_rows = x9_to_json(x9_file)
                for record in forward_rows:
                    fw_file.write(f"{json.dumps(record)}\n")
                for record in return_rows:
                    ret_file.write(f"{json.dumps(record)}\n")
            except Exception as e:
                print(f"Warning: Failed to convert {x9_file}: {e}")
    print("Conversion complete\n")

    df_all_forward = load_jsonl_df(forward_json_file)
    df_return = load_jsonl_df(return_json_file)

    default_forward_columns = [
        "filename",
        "25_payor_bank_routing_number",
        "25_payor_bank_routing_number_check_digit",
        "26_bofd_routing_number",
        "25_item_amount",
        "25_on_us",
        "25_auxiliary_on_us",
        "25_ece_institution_item_sequence_number",
        "20_bundle_business_date",
    ]
    if df_all_forward.empty:
        df_forward = pd.DataFrame(columns=default_forward_columns)
    else:
        if "25_item_amount" in df_all_forward.columns:
            df_forward = df_all_forward[df_all_forward["25_item_amount"].notna()].copy()
        else:
            df_forward = pd.DataFrame(columns=default_forward_columns)

    print(f"Forward: {len(df_forward):,}, Return: {len(df_return):,}\n")

    if not df_forward.empty:
        df_forward.to_csv(f"forward_result_{current_time}.tsv", sep="\t", index=False)
    if not df_return.empty:
        df_return.to_csv(f"return_result_{current_time}.tsv", sep="\t", index=False)
    elif any(r["return_records_present"] for r in structure_results):
        # Keep a predictable artifact for return-only runs.
        pd.DataFrame().to_csv(f"return_result_{current_time}.tsv", sep="\t", index=False)

    # ============================================================
    # SECTION 1: FILE & DATA QUALITY
    # ============================================================
    log_header("X9 Check Validation Report", file_count)

    header_fail_files_pre = sum(1 for r in structure_results if not r["header_ok"])
    header_status = "PASS" if header_fail_files_pre == 0 else "FAIL"
    log_check(
        "Header Hierarchy Check (01 -> 10 -> 20)",
        header_status,
        (
            f"Files scanned: {file_count:,}\n"
            f"Files with valid header sequence: {file_count - header_fail_files_pre:,}\n"
            f"Files failing header sequence: {header_fail_files_pre:,}"
        ),
        "Each X9 file should begin with File Header 01, Cash Letter Header 10, and Bundle Header 20.",
    )

    log_check(
        "Hierarchical UI Report Export",
        "INFO",
        (
            f"Hierarchical JSON generated for {len(hierarchical_reports):,} files.\n"
            f"Path: {hierarchical_report_path}"
        ),
        "Use this artifact for UI drill-down: file -> cash letter -> bundle -> item -> record details.",
    )

    # 1.1 Data Continuity
    if enable_date_continuity:
        file_names = [os.path.basename(f) for f in x9_files]
        dates = sorted(
            {
                token
                for f in file_names
                for token in extract_valid_yyyymmdd_tokens(f)
            }
        )
        if dates and len(dates) > 1:
            start_date = datetime.strptime(str(dates[0]), "%Y%m%d")
            end_date = datetime.strptime(str(dates[-1]), "%Y%m%d")
            weekdays_list = weekdays_between_dates(start_date, end_date)
            required_dates = [d.strftime("%Y%m%d") for d in weekdays_list]
            missing_dates = set(required_dates) - set(dates)
            if len(missing_dates) == 0:
                log_check(
                    "Data Continuity Check",
                    "PASS",
                    f"Data is continuous from {dates[0]} to {dates[-1]}",
                    "No action required.",
                )
            else:
                log_check(
                    "Data Continuity Check",
                    "WARN",
                    f"Missing business dates: {sorted(missing_dates)}",
                    "Confirm if these are holidays. If not, check with customer.",
                )
        else:
            log_check(
                "Data Continuity Check",
                "INFO",
                "Not enough dated files to evaluate continuity.",
                "Informational only.",
            )
    else:
        log_check(
            "Data Continuity Check",
            "INFO",
            "Skipped by configuration (enable_date_continuity=false).",
            "Enable date continuity if date-gap monitoring is required.",
        )

    # 1.2 Structural and Phase-1 Basic Validation Summary
    header_fail_files = sum(1 for r in structure_results if not r["header_ok"])
    orphan_26_total = sum(r["orphan_26_count"] for r in structure_results)
    missing_26_total = sum(r["missing_26_after_25_count"] for r in structure_results)
    missing_26_detail_total = sum(r.get("missing_26_detail_count", 0) for r in structure_results)
    files_missing_presentment_required = sum(1 for r in structure_results if r["missing_presentment_types"])
    files_missing_return_required = sum(
        1 for r in structure_results if r["return_mode"] and r["missing_return_types"]
    )
    files_with_critical_field_errors = sum(1 for r in structure_results if r["critical_field_error_count"] > 0)
    critical_field_error_total = sum(r["critical_field_error_count"] for r in structure_results)
    files_with_collection_01 = sum(1 for r in structure_results if "01" in r["collection_type_values"])
    files_with_collection_03 = sum(1 for r in structure_results if "03" in r["collection_type_values"])
    presentment_mode_files = sum(1 for r in structure_results if r["presentment_mode"])
    return_mode_files = sum(1 for r in structure_results if r["return_mode"])
    required_record_type_totals = {
        rt: sum(r["record_type_counts"].get(rt, 0) for r in structure_results)
        for rt in TRACKED_RECORD_TYPES
    }

    presentment_item_count = sum(r["presentment_item_count"] for r in structure_results)
    return_item_count = sum(r["return_item_count"] for r in structure_results)
    presentment_items_without_front_image_total = sum(
        r["presentment_items_without_front_image"] for r in structure_results
    )
    return_items_without_front_image_total = sum(
        r["return_items_without_front_image"] for r in structure_results
    )
    presentment_items_without_pair_total = sum(
        r["presentment_items_without_image_pair"] for r in structure_results
    )
    return_items_without_pair_total = sum(
        r["return_items_without_image_pair"] for r in structure_results
    )

    invalid_files_count = len(invalid_file_rows)
    structure_status = "PASS" if invalid_files_count == 0 else "FAIL"
    detail_lines = [
        f"Files scanned: {file_count:,}",
        f"Valid files: {len(valid_x9_files):,}",
        f"Invalid files: {invalid_files_count:,}",
        f"Files failing 01->10->20 header sequence: {header_fail_files:,}",
        f"Orphan 26 records (26 without preceding 25): {orphan_26_total:,}",
        f"25 records missing corresponding 26: {missing_26_total:,}",
        f"Missing-26 pinpoint records captured: {missing_26_detail_total:,}",
        f"Collection type 01 files: {files_with_collection_01:,}",
        f"Collection type 03 files: {files_with_collection_03:,}",
    ]
    if invalid_structure_report:
        detail_lines.append(f"Invalid file report: {invalid_structure_report}")
    if missing_26_detail_report:
        detail_lines.append(f"Missing-26 detail report: {missing_26_detail_report}")
    if invalid_file_rows:
        preview = "\n".join(
            [f" - {r['filename']}: {r.get('issues_preview', 'No details')}" for r in invalid_file_rows[:5]]
        )
        detail_lines.append(f"Sample issues:\n{preview}")

    log_check(
        "Record Structure Check (Header + 25/26 Ordering)",
        structure_status,
        "\n".join(detail_lines),
        "X9 file must start with 01->10->20, each 26 must follow 25, and each 25 must include at least one 26.",
    )

    missing_26_detail_status = "PASS" if missing_26_detail_total == 0 else "WARN"
    missing_26_examples = []
    for result in structure_results:
        for item in result.get("missing_26_details", []):
            missing_26_examples.append(
                (
                    f"{item['filename']}: id={item.get('unique_check_id', '')}, line25={item['line_25']}, bundle={item['bundle_id']}, "
                    f"bundle_date={item['bundle_business_date']}, check_number={item['check_number']}, "
                    f"reason={item['reason']}"
                )
            )
            if len(missing_26_examples) >= 10:
                break
        if len(missing_26_examples) >= 10:
            break
    missing_26_lines = [f"Total missing 25->26 cases: {missing_26_detail_total:,}"]
    if missing_26_detail_report:
        missing_26_lines.append(f"Detail report: {missing_26_detail_report}")
    if missing_26_examples:
        missing_26_lines.append("Examples:\n - " + "\n - ".join(missing_26_examples))
    log_check(
        "Missing 26 Pinpoint Report (Batch/Bundle/Check Number)",
        missing_26_detail_status,
        "\n".join(missing_26_lines),
        "Use detail report to pinpoint each 25 missing 26 by bundle and check number.",
    )

    required_record_status = (
        "PASS"
        if files_missing_presentment_required == 0 and files_missing_return_required == 0
        else "FAIL"
    )
    required_examples = []
    for result in structure_results:
        if result["missing_presentment_types"]:
            required_examples.append(
                f"{result['file']}: presentment missing {','.join(result['missing_presentment_types'])}"
            )
        if result["return_mode"] and result["missing_return_types"]:
            required_examples.append(
                f"{result['file']}: return missing {','.join(result['missing_return_types'])}"
            )
        if len(required_examples) >= 10:
            break
    required_details = [
        "Collection-aware required record type presence.",
        (
            "Tracked record totals: "
            + ", ".join([f"{rt}={required_record_type_totals[rt]:,}" for rt in TRACKED_RECORD_TYPES])
        ),
        (
            "Presentment mode files (01 or 25/26 detected): "
            f"{presentment_mode_files:,} | Missing presentment required set (25/26/50/52): "
            f"{files_missing_presentment_required:,}"
        ),
        (
            "Return mode files (03 or 31/32 detected): "
            f"{return_mode_files:,} | Missing return required set (31/32/50/52): "
            f"{files_missing_return_required:,}"
        ),
    ]
    if return_mode_files == 0:
        required_details.append("No return records detected; return record-set validation is optional and not required.")
    if required_examples:
        required_details.append("Examples:\n - " + "\n - ".join(required_examples))
    log_check(
        "Basic Validation: Required Record Types by Collection Type",
        required_record_status,
        "\n".join(required_details),
        "01 files require 25/26/50/52. 03 files require 31/32/50/52. Return absence does not fail validation.",
    )

    critical_status = "PASS" if critical_field_error_total == 0 else "FAIL"
    critical_examples = []
    for result in structure_results:
        if result["critical_field_error_count"] > 0 and result["issues"]:
            first_match = next(
                (
                    issue
                    for issue in result["issues"]
                    if "invalid/missing" in issue
                    or "missing " in issue
                    or "checksum" in issue
                    or "invalid ABA" in issue
                ),
                "",
            )
            if first_match:
                critical_examples.append(f"{result['file']}: {first_match}")
        if len(critical_examples) >= 10:
            break
    critical_details = [
        "Critical fields validated for presentment (25/26) and return (31/32 when present).",
        "Includes routing transit number format/checksum, account number presence, and MICR data checks.",
        f"Files with critical field issues: {files_with_critical_field_errors:,}",
        f"Total critical field issues: {critical_field_error_total:,}",
    ]
    if critical_examples:
        critical_details.append("Examples:\n - " + "\n - ".join(critical_examples))
    log_check(
        "Basic Validation: Critical Fields Presence",
        critical_status,
        "\n".join(critical_details),
        "Critical fields (ABA RTNs, account numbers, and MICR data) must be populated and valid.",
    )

    image_status = (
        "FAIL"
        if (presentment_items_without_front_image_total + return_items_without_front_image_total) > 0
        else (
            "WARN"
            if (presentment_items_without_pair_total + return_items_without_pair_total) > 0
            else "PASS"
        )
    )
    image_details = [
        "Per-item image linkage validation (RT25/RT31 context).",
        "Required: at least one record 50 per item. Advisory: record 52 should also be present.",
        f"Presentment items detected (RT25): {presentment_item_count:,}",
        f"Return items detected (RT31): {return_item_count:,}",
        (
            "Missing record 50 (no image): "
            f"presentment={presentment_items_without_front_image_total:,}, "
            f"return={return_items_without_front_image_total:,}"
        ),
        (
            "Missing record 52 with record 50 present (advisory): "
            f"presentment={presentment_items_without_pair_total:,}, "
            f"return={return_items_without_pair_total:,}"
        ),
    ]
    if return_item_count == 0:
        image_details.append("No return items detected.")
    log_check(
        "Basic Validation: Item Image Linkage (25/31 with 50/52)",
        image_status,
        "\n".join(image_details),
        "Each RT25/RT31 item should carry at least one RT50. RT52 is tracked as image-block completeness.",
    )

    # 1.3 Bad Record Check (moved after structural checks to reduce front-of-report noise)
    bad_record_perc = round((bad_record_cnt / total_record_cnt) * 100, 2) if total_record_cnt else 0
    status = "FAIL" if bad_record_perc > bad_record_threshold else "PASS"
    log_check(
        "Bad Record Check (Syntax/Internal Count)",
        status,
        (
            f"Total records scanned: {total_record_cnt:,}\n"
            f"Bad records found: {bad_record_cnt:,}\n"
            f"Bad record percentage: {bad_record_perc}%\n"
            f"Configured threshold: {bad_record_threshold}%\n"
            "Note: syntax count is tracked for diagnostics and appears after header/structure checks."
        ),
        "FAIL if bad record percentage exceeds threshold.",
    )

    # 1.4 Record Type Summary
    log_check(
        "Credit Records Check (RT 62)",
        "INFO",
        "N/A (X937 format does not separate RT 62 in this parser)",
        "Informational only.",
    )
    log_check(
        "Return Records Count",
        "INFO",
        f"Count = {df_return.shape[0]:,}",
        "Review if returns look normal.",
    )
    log_check(
        "Legit/Forward Records",
        "INFO",
        f"Count = {len(df_forward):,}",
        "Used for further validation.",
    )

    log_summary("File & Data Quality")

    return_records_present = any(r["return_records_present"] for r in structure_results) or not df_return.empty
    if df_forward.empty:
        if return_records_present:
            log_check(
                "Forward Record Availability",
                "INFO",
                "No valid presentment records (RT25) found after structure validation; proceeding with return validation.",
                "Return files are optional and may appear separately from presentment files.",
            )
            # In return-only runs, skip forward-focused sections to avoid confusing 0/NaN stats.
            phase2_results = run_phase2_field_level_checks(df_forward, df_return)
            for check_name, status, details, guideline in phase2_results:
                log_check(check_name, status, details, guideline)
            log_summary("Phase 2 - Field-Level Validation by Record Type")
            log_check(
                "Forward-Focused Sections Skipped",
                "INFO",
                "Sections 2-5 (transaction distribution, amount, field structure, and forward data integrity) skipped because no RT25 presentment records were found.",
                "This is expected for return-only datasets.",
            )

            # Continue with return validation section only.
            if df_return.shape[0] > 0:
                log_check(
                    "Return Records Summary",
                    "INFO",
                    f"Processing {len(df_return):,} return records",
                    "Review return records for patterns indicating systemic issues.",
                )

                if (
                    "31_payor_bank_routing_number" in df_return.columns
                    and "31_payor_bank_routing_number_check_digit" in df_return.columns
                ):
                    df_return["RETURN_PAYOR_ROUTING"] = _normalize_text_series(
                        df_return, "31_payor_bank_routing_number"
                    ) + _normalize_text_series(df_return, "31_payor_bank_routing_number_check_digit")

                required_fields = [
                    "RETURN_PAYOR_ROUTING",
                    "31_on_us_return_record",
                    "32_bofd_routing_number",
                    "32_deposit_account_number_at_bofd",
                ]
                existing_required = [f for f in required_fields if f in df_return.columns]
                missing_counts = {}
                normalized_return_fields = {}
                for field in existing_required:
                    normalized = _normalize_text_series(df_return, field)
                    normalized_return_fields[field] = normalized
                    missing_counts[field] = int((normalized == "").sum())
                for field, count in missing_counts.items():
                    log_check(
                        f"Return Records Missing Value Check: {field}",
                        "FAIL" if count > 0 else "PASS",
                        f"{count:,} missing/blank values in {field}",
                        "There should be no missing values. Investigate if count > 0.",
                    )

                for field in existing_required:
                    top_vals = normalized_return_fields[field][
                        normalized_return_fields[field] != ""
                    ].value_counts().head(5)
                    if not top_vals.empty:
                        details_df = top_vals.reset_index()
                        details_df.columns = ["Value", "Count"]
                        log_check(
                            f"Return Records Top Values: {field}",
                            "INFO",
                            f"\n{details_df.to_string(index=False)}",
                            "Review if these values are expected.",
                        )

                if "31_return_reason" in df_return.columns:
                    reason_counts = df_return["31_return_reason"].value_counts().head(10)
                    if not reason_counts.empty:
                        reason_df = reason_counts.reset_index()
                        reason_df.columns = ["Return_Reason", "Count"]
                        log_check(
                            "Return Records Return Reason Distribution",
                            "INFO",
                            f"Top return reasons:\n{reason_df.to_string(index=False)}",
                            "Review if return reasons indicate systematic issues.",
                        )

                if "35_endorsing_bank_endorsement_date" in df_return.columns:
                    endorsement_dates = pd.to_datetime(
                        df_return["35_endorsing_bank_endorsement_date"],
                        format="%Y%m%d",
                        errors="coerce",
                    ).dropna()
                    if not endorsement_dates.empty:
                        log_check(
                            "Return Records Endorsement Date Range",
                            "INFO",
                            (
                                f"Endorsement dates from {endorsement_dates.min().date()} "
                                f"to {endorsement_dates.max().date()}"
                            ),
                            "Ensure dates align with data collection period.",
                        )

            log_summary("Return Records Validation")
            log_individual_check_results()
            log_footer(check_results["FAIL"], check_results["WARN"])
            log_section_end("SECTION 1 X937 RDV VALIDATION TEST")
            print("\nX937 validation completed.")
            return
        else:
            log_check(
                "Forward Record Availability",
                "FAIL",
                "No valid forward records available after structure and syntax validation.",
                "Review invalid_x937_structure report and source files.",
            )
            log_summary("Processing Availability")
            log_individual_check_results()
            log_footer(check_results["FAIL"], check_results["WARN"])
            log_section_end("SECTION 1 X937 RDV VALIDATION TEST")
            print("\nX937 validation completed with critical issues.")
            return

    # ============================================================
    # SECTION 2: TRANSACTION CLASSIFICATION & DISTRIBUTION
    # ============================================================
    payor_rt_series = _normalize_text_series(df_forward, "25_payor_bank_routing_number")
    payor_cd_series = _normalize_text_series(df_forward, "25_payor_bank_routing_number_check_digit")
    bofd_rt_series = _normalize_text_series(df_forward, "26_bofd_routing_number")
    on_us_series = _normalize_text_series(df_forward, "25_on_us").str.strip("/")
    aux_on_us_series = _normalize_text_series(df_forward, "25_auxiliary_on_us")
    on_us_last_series = on_us_series.apply(lambda value: value.split("/")[-1] if value else "")

    df_forward["PAYOR_ROUTING"] = payor_rt_series + payor_cd_series
    df_forward["BOFD_ROUTING"] = bofd_rt_series
    df_forward["VALID_ROUTING"] = (
        payor_rt_series.str.fullmatch(r"\d{8}")
        & payor_cd_series.str.fullmatch(r"\d")
        & bofd_rt_series.str.fullmatch(r"\d{9}")
    )
    df_forward["25_on_us"] = on_us_series
    df_forward["25_auxiliary_on_us"] = aux_on_us_series
    df_forward["payer_account"] = on_us_series.str.split("/").str[0].fillna("")
    df_forward["check_number"] = aux_on_us_series.where(aux_on_us_series != "", on_us_last_series)
    df_forward["TRANSACTION_TYPE"] = df_forward.apply(lambda row: classify_transaction(row, our_aba_list), axis=1)
    df_forward["CR_DR_FLAG"] = df_forward.apply(lambda row: credit_debit_flag(row, our_aba_list), axis=1)
    df_forward["ITEM_AMOUNT_FLOAT"] = pd.to_numeric(df_forward["25_item_amount"], errors="coerce") / 100
    df_forward["onus_elements"] = on_us_series.apply(
        lambda value: len([part for part in value.split("/") if part]) if value else 0
    )

    withdrawals = df_forward[df_forward["TRANSACTION_TYPE"] == "WITHDRAWAL"]
    deposits = df_forward[df_forward["TRANSACTION_TYPE"] == "DEPOSIT"]
    on_us = df_forward[df_forward["TRANSACTION_TYPE"] == "ON_US"]
    total = len(df_forward)

    log_check(
        "Transaction Type Distribution",
        "INFO",
        (
            f"Withdrawals: {len(withdrawals):,} ({round(len(withdrawals)/total*100,2) if total else 0}%)\n"
            f"Deposits: {len(deposits):,} ({round(len(deposits)/total*100,2) if total else 0}%)\n"
            f"ON_US: {len(on_us):,} ({round(len(on_us)/total*100,2) if total else 0}%)\n"
            f"TOTAL: {total:,}"
        ),
        "Direction model uses three buckets: DEPOSIT, ON_US, WITHDRAWAL.",
    )

    payor_is_ours_series = df_forward["PAYOR_ROUTING"].isin(our_aba_list)
    bofd_is_ours_series = df_forward["BOFD_ROUTING"].isin(our_aba_list)
    both_external = df_forward[~payor_is_ours_series & ~bofd_is_ours_series]
    payor_ours_bofd_external = df_forward[payor_is_ours_series & ~bofd_is_ours_series]
    payor_external_bofd_ours = df_forward[~payor_is_ours_series & bofd_is_ours_series]
    on_us_combo = df_forward[payor_is_ours_series & bofd_is_ours_series]
    missing_payor_routing = (df_forward["PAYOR_ROUTING"] == "").sum()
    missing_bofd_routing = (df_forward["BOFD_ROUTING"] == "").sum()
    both_external_sample_pairs = (
        both_external[["PAYOR_ROUTING", "BOFD_ROUTING"]]
        .drop_duplicates()
        .head(10)
        .to_string(index=False)
        if not both_external.empty
        else "None"
    )
    log_check(
        "Direction Classification Diagnostics (ABA-based)",
        "INFO",
        (
            "Direction definitions:\n"
            " - ON_US: PAYOR_ROUTING in our ABA list and BOFD_ROUTING in our ABA list\n"
            " - DEPOSIT: PAYOR_ROUTING not in our ABA list and BOFD_ROUTING in our ABA list\n"
            " - WITHDRAWAL: all remaining records (including both-external payor/bofd)\n"
            f"ABA combination counts:\n"
            f" - payor=ours, bofd=ours (ON_US): {len(on_us_combo):,}\n"
            f" - payor=external, bofd=ours (DEPOSIT): {len(payor_external_bofd_ours):,}\n"
            f" - payor=ours, bofd=external (WITHDRAWAL): {len(payor_ours_bofd_external):,}\n"
            f" - payor=external, bofd=external (mapped to WITHDRAWAL): {len(both_external):,}\n"
            f"Missing PAYOR_ROUTING after normalization: {missing_payor_routing:,}\n"
            f"Missing BOFD_ROUTING after normalization: {missing_bofd_routing:,}\n"
            f"Sample both-external payor/bofd routing pairs (Top 10):\n{both_external_sample_pairs}"
        ),
        "Use this to validate direction logic and confirm ABA mapping is correct.",
    )

    direction_counts = {
        "WITHDRAWAL": len(withdrawals),
        "DEPOSIT": len(deposits),
        "ON_US": len(on_us),
    }
    active_directions = [name for name, count in direction_counts.items() if count > 0]
    direction_mix_status = "WARN" if total >= 1000 and len(active_directions) <= 1 else "INFO"
    log_check(
        "Direction Mix Sanity Check",
        direction_mix_status,
        (
            f"Active directions: {', '.join(active_directions) if active_directions else 'None'}\n"
            f"Counts: WITHDRAWAL={direction_counts['WITHDRAWAL']:,}, "
            f"DEPOSIT={direction_counts['DEPOSIT']:,}, ON_US={direction_counts['ON_US']:,}\n"
            f"Total forward records: {total:,}"
        ),
        "If a long date range shows only one direction, verify ABA list/config and source feed composition.",
    )

    credit_count = (df_forward["CR_DR_FLAG"] == "CREDIT").sum()
    debit_count = (df_forward["CR_DR_FLAG"] == "DEBIT").sum()
    external_count = (df_forward["CR_DR_FLAG"] == "EXTERNAL").sum()
    unknown_count = (df_forward["CR_DR_FLAG"] == "UNKNOWN").sum()
    log_check(
        "Credit/Debit Distribution",
        "INFO",
        (
            f"CREDIT records: {credit_count:,}\n"
            f"DEBIT records: {debit_count:,}\n"
            f"EXTERNAL records (neither routing matches our ABA): {external_count:,}\n"
            f"UNKNOWN records: {unknown_count:,}\n"
            f"TOTAL: {total:,}"
        ),
        "Verify credit/debit distribution aligns with expected transaction flow.",
    )

    for txn_df, label in [
        (withdrawals, "Withdrawals"),
        (deposits, "Deposits"),
        (on_us, "ON_US Transactions"),
    ]:
        if len(txn_df) > 0:
            top_df = top_10(txn_df)
            if not top_df.empty:
                log_check(
                    f"Top 10 {label}",
                    "INFO",
                    f"\n{top_df.to_string(index=False)}",
                    f"Review high-volume {label.lower()} patterns.",
                )

    invalid_routing_count = (~df_forward["VALID_ROUTING"]).sum()
    log_check(
        "Routing Number Format Validation",
        "PASS" if invalid_routing_count == 0 else "WARN",
        (
            f"Total records: {len(df_forward):,}\n"
            f"Records with invalid routing numbers: {invalid_routing_count:,}\n"
            f"Invalid routing percentage: "
            f"{round(invalid_routing_count/len(df_forward)*100,2) if len(df_forward) else 0}%"
        ),
        "Payor routing should be 9 digits, BOFD routing should be 9 digits. Review if invalid count > 0.",
    )

    log_summary("Transaction Classification & Distribution")

    # ============================================================
    # PHASE 2: FIELD-LEVEL VALIDATION BY RECORD TYPE
    # ============================================================
    phase2_results = run_phase2_field_level_checks(df_forward, df_return)
    for check_name, status, details, guideline in phase2_results:
        log_check(check_name, status, details, guideline)
    log_summary("Phase 2 - Field-Level Validation by Record Type")

    # ============================================================
    # SECTION 3: AMOUNT VALIDATION
    # ============================================================
    valid_amount_series = df_forward["ITEM_AMOUNT_FLOAT"].dropna()
    if valid_amount_series.empty:
        log_check(
            "Amount Distribution Statistics",
            "INFO",
            (
                f"Count: 0\n"
                "No valid numeric forward amounts available to compute distribution statistics."
            ),
            "Amount stats skipped to avoid NaN output; investigate blank/non-numeric RT25 item amounts.",
        )
    else:
        amount_stats = valid_amount_series.describe()
        log_check(
            "Amount Distribution Statistics",
            "INFO",
            (
                f"Count: {int(amount_stats['count']):,}\n"
                f"Mean: ${amount_stats['mean']:.2f}\n"
                f"Median: ${valid_amount_series.median():.2f}\n"
                f"Min: ${amount_stats['min']:.2f}\n"
                f"Max: ${amount_stats['max']:.2f}\n"
                f"Std Dev: ${amount_stats['std']:.2f}"
            ),
            "Review outliers and ensure amounts align with expected transaction patterns.",
        )

    zero_amounts = df_forward[df_forward["ITEM_AMOUNT_FLOAT"] == 0]
    zero_pct = round(len(zero_amounts) / len(df_forward) * 100, 2) if len(df_forward) else 0
    status = "PASS" if len(zero_amounts) == 0 else ("WARN" if not allow_zero else "INFO")
    log_check(
        "Zero Amount Check",
        status,
        f"{len(zero_amounts):,} records with zero amount ({zero_pct}%)",
        (
            "Zero amounts may indicate test records or data issues. Verify with customer if count > 0."
            if not allow_zero
            else "Zero amounts are allowed per configuration."
        ),
    )

    missing_amounts = df_forward[df_forward["ITEM_AMOUNT_FLOAT"].isna()]
    missing_pct = round(len(missing_amounts) / len(df_forward) * 100, 2) if len(df_forward) else 0
    status = "PASS" if len(missing_amounts) == 0 else ("FAIL" if not allow_missing else "INFO")
    log_check(
        "Missing Amount Check",
        status,
        f"{len(missing_amounts):,} records with missing amount ({missing_pct}%)",
        (
            "All records must have valid amounts. Investigate source data if count > 0."
            if not allow_missing
            else "Missing amounts are allowed per configuration."
        ),
    )

    if enable_outlier_detection:
        df_amount_valid = df_forward[df_forward["ITEM_AMOUNT_FLOAT"].notna()]
        if len(df_amount_valid) > 0:
            q1 = df_amount_valid["ITEM_AMOUNT_FLOAT"].quantile(0.25)
            q3 = df_amount_valid["ITEM_AMOUNT_FLOAT"].quantile(0.75)
            iqr = q3 - q1
            outliers = df_amount_valid[
                (df_amount_valid["ITEM_AMOUNT_FLOAT"] < q1 - iqr_multiplier * iqr)
                | (df_amount_valid["ITEM_AMOUNT_FLOAT"] > q3 + iqr_multiplier * iqr)
            ]
            if len(outliers) > 0:
                top_outliers = outliers.nlargest(10, "ITEM_AMOUNT_FLOAT")[
                    ["25_on_us", "PAYOR_ROUTING", "BOFD_ROUTING", "ITEM_AMOUNT_FLOAT"]
                ].copy()
                top_outliers["ITEM_AMOUNT_FLOAT"] = top_outliers["ITEM_AMOUNT_FLOAT"].apply(
                    lambda x: f"${x:.2f}"
                )
                log_check(
                    "Amount Outlier Detection",
                    "INFO",
                    (
                        f"{len(outliers):,} statistical outliers detected (>{iqr_multiplier} IQR)\n\n"
                        f"Top 10 by amount:\n{top_outliers.to_string(index=False)}"
                    ),
                    "Review high-value transactions for legitimacy.",
                )
            else:
                log_check(
                    "Amount Outlier Detection",
                    "PASS",
                    "No statistical outliers detected",
                    "No action required.",
                )

    log_summary("Amount Validation")

    # ============================================================
    # SECTION 4: FIELD STRUCTURE VALIDATION
    # ============================================================
    invalid_onus = df_forward[df_forward["onus_elements"] > onus_max]
    invalid_onus_pct = round(len(invalid_onus) / len(df_forward) * 100, 2) if len(df_forward) else 0
    log_check(
        "ON_US Field Structure Validation",
        "WARN" if len(invalid_onus) > 0 else "PASS",
        f"{len(invalid_onus):,} records have more than {onus_max} ON_US elements ({invalid_onus_pct}%)",
        f"ON_US field should contain fewer than {onus_max} slash-separated elements.",
    )

    aux_populated_count = (df_forward["25_auxiliary_on_us"] != "").sum()
    on_us_populated_count = (df_forward["25_on_us"] != "").sum()
    aux_percentage = round(aux_populated_count / len(df_forward) * 100, 2) if len(df_forward) else 0
    log_check(
        "Auxiliary ON_US Population",
        "INFO",
        (
            f"RT25 records considered: {len(df_forward):,}\n"
            f"AUX ON_US populated: {aux_populated_count:,} ({aux_percentage}%)\n"
            f"ON_US populated: {on_us_populated_count:,} "
            f"({round(on_us_populated_count / len(df_forward) * 100, 2) if len(df_forward) else 0}%)"
        ),
        "Percentages are based on RT25 records only (not total physical X9 records).",
    )
    micr_both_populated = ((df_forward["25_auxiliary_on_us"] != "") & (df_forward["25_on_us"] != "")).sum()
    micr_aux_only = ((df_forward["25_auxiliary_on_us"] != "") & (df_forward["25_on_us"] == "")).sum()
    micr_onus_only = ((df_forward["25_auxiliary_on_us"] == "") & (df_forward["25_on_us"] != "")).sum()
    micr_neither = ((df_forward["25_auxiliary_on_us"] == "") & (df_forward["25_on_us"] == "")).sum()
    log_check(
        "MICR Source Mix (ON_US vs AUX ON_US)",
        "INFO",
        (
            f"Both ON_US and AUX ON_US populated: {micr_both_populated:,}\n"
            f"AUX ON_US only (business-account style): {micr_aux_only:,}\n"
            f"ON_US only (personal-account style): {micr_onus_only:,}\n"
            f"Neither populated: {micr_neither:,}"
        ),
        "Use this mix to validate whether ON_US/AUX_ON_US behavior matches customer feed expectations.",
    )

    probable_non_check_mask = (
        (df_forward["25_auxiliary_on_us"] == "")
        & ((df_forward["payer_account"] == "") | (df_forward["25_on_us"] == ""))
    )
    probable_non_check_df = df_forward[probable_non_check_mask].copy()
    probable_non_check_pct = (
        round(len(probable_non_check_df) / len(df_forward) * 100, 2) if len(df_forward) else 0
    )
    if not probable_non_check_df.empty:
        non_check_top = probable_non_check_df["filename"].value_counts().head(10).reset_index()
        non_check_top.columns = ["filename", "probable_non_check_count"]
        log_check(
            "Probable Non-Check / Deposit-Slip Indicators",
            "WARN",
            (
                f"Records flagged by heuristic: {len(probable_non_check_df):,} ({probable_non_check_pct}%)\n"
                "Heuristic: AUX ON_US missing and ON_US/payer_account missing.\n"
                f"Top files:\n{non_check_top.to_string(index=False)}"
            ),
            "These may be deposit slips or other non-check items; review duplicate analysis after excluding them.",
        )
    else:
        log_check(
            "Probable Non-Check / Deposit-Slip Indicators",
            "INFO",
            "No records matched the non-check heuristic (AUX ON_US missing + ON_US/payer_account missing).",
            "Informational heuristic only; adjust logic if customer format differs.",
        )

    log_summary("Field Structure Validation")

    # ============================================================
    # SECTION 5: DATA INTEGRITY CHECKS
    # ============================================================
    if enable_duplicate_check:
        blank_key_cnt = ((df_forward["payer_account"] == "") | (df_forward["check_number"] == "")).sum()
        duplicate_key = ["payer_account", "check_number"]
        duplicate_pool = df_forward[
            (df_forward["payer_account"] != "") & (df_forward["check_number"] != "")
        ].copy()
        is_duplicated = duplicate_pool.duplicated(subset=duplicate_key, keep=False)
        df_duplicates = duplicate_pool[is_duplicated].copy()

        if not df_duplicates.empty:
            df_checknum_counts = (
                df_duplicates.groupby(duplicate_key)
                .agg(
                    count=("check_number", "size"),
                    sample_sequence_numbers=(
                        "25_ece_institution_item_sequence_number",
                        lambda values: " | ".join(_unique_non_empty(values, limit=5)),
                    ),
                    sample_item_amounts=(
                        "25_item_amount",
                        lambda values: " | ".join(_unique_non_empty(values, limit=5)),
                    ),
                    sample_bundle_dates=(
                        "20_bundle_business_date",
                        lambda values: " | ".join(_unique_non_empty(values, limit=3)),
                    ),
                    sample_files=(
                        "filename",
                        lambda values: " | ".join(_unique_non_empty(values, limit=3)),
                    ),
                )
                .reset_index()
                .sort_values(by="count", ascending=False)
            )
            threshold = 10
            high_volume_duplicates = df_checknum_counts[df_checknum_counts["count"] > threshold]
            df_duplicates["sequence_number"] = _normalize_text_series(
                df_duplicates, "25_ece_institution_item_sequence_number"
            )
            df_duplicates["item_amount_dollars"] = (
                pd.to_numeric(df_duplicates["25_item_amount"], errors="coerce") / 100
            ).round(2)
            sample_duplicate_rows = (
                df_duplicates[
                    [
                        "filename",
                        "payer_account",
                        "check_number",
                        "sequence_number",
                        "item_amount_dollars",
                        "20_bundle_business_date",
                    ]
                ]
                .sort_values(
                    by=["payer_account", "check_number", "filename", "sequence_number"],
                    ascending=True,
                )
                .head(25)
            )
            log_check(
                "Duplicate Check Number Check (payer_account + check_number)",
                "WARN",
                (
                    f"Records excluded due to blank duplicate key fields: {blank_key_cnt:,}\n"
                    f"Records included in duplicate pool: {len(duplicate_pool):,}\n"
                    f"Total duplicate records: {len(df_duplicates):,}\n"
                    f"Unique duplicate check combinations: {len(df_checknum_counts):,}\n\n"
                    "Top 20 duplicate checks (with sample sequence numbers/amounts/files):\n"
                    f"{df_checknum_counts.head(20).to_string(index=False)}\n\n"
                    "Sample duplicate rows for investigation (filename/account/check/sequence):\n"
                    f"{sample_duplicate_rows.to_string(index=False)}\n\n"
                    f"High volume duplicates (count > {threshold}): {len(high_volume_duplicates)}\n"
                    f"{high_volume_duplicates.to_string(index=False) if not high_volume_duplicates.empty else 'None'}"
                ),
                "Duplicate checks identified. High volume duplicates may indicate systematic issues.",
            )
            tracking_fields = [
                "payer_account",
                "check_number",
                "filename",
                "sequence_number",
                "25_ece_institution_item_sequence_number",
                "25_item_amount",
                "item_amount_dollars",
                "20_bundle_business_date",
            ]
            df_duplicates[tracking_fields].to_csv(
                f"duplicate_checks_detail_{current_time}.tsv",
                sep="\t",
                index=False,
            )
            log_check(
                "Duplicate Check Investigation Artifact",
                "INFO",
                f"Detailed duplicate rows exported: duplicate_checks_detail_{current_time}.tsv",
                "Use filename + payer_account + check_number + sequence_number to trace duplicate source.",
            )
        else:
            log_check(
                "Duplicate Check Number Check (payer_account + check_number)",
                "PASS",
                "No duplicate checks found.",
                "No action required.",
            )
        onus_duplicate_pool = df_forward[df_forward["25_on_us"] != ""].copy()
        onus_is_duplicated = onus_duplicate_pool.duplicated(subset=["25_on_us"], keep=False)
        onus_duplicates = onus_duplicate_pool[onus_is_duplicated].copy()
        if not onus_duplicates.empty:
            onus_duplicates["sequence_number"] = _normalize_text_series(
                onus_duplicates, "25_ece_institution_item_sequence_number"
            )
            onus_counts = (
                onus_duplicates.groupby("25_on_us")
                .agg(
                    count=("25_on_us", "size"),
                    sample_files=("filename", lambda values: " | ".join(_unique_non_empty(values, limit=3))),
                    sample_sequences=(
                        "25_ece_institution_item_sequence_number",
                        lambda values: " | ".join(_unique_non_empty(values, limit=5)),
                    ),
                )
                .reset_index()
                .sort_values(by="count", ascending=False)
            )
            onus_tracking_fields = [
                "filename",
                "25_on_us",
                "payer_account",
                "check_number",
                "sequence_number",
                "25_auxiliary_on_us",
                "25_item_amount",
                "20_bundle_business_date",
            ]
            onus_duplicates[onus_tracking_fields].to_csv(
                f"onus_duplicates_detail_{current_time}.tsv",
                sep="\t",
                index=False,
            )
            log_check(
                "ON_US Duplicate Pattern Check (Deposit-Slip Lead)",
                "WARN",
                (
                    f"Duplicate ON_US records: {len(onus_duplicates):,}\n"
                    f"Unique duplicated ON_US values: {len(onus_counts):,}\n"
                    f"Top duplicated ON_US values:\n{onus_counts.head(20).to_string(index=False)}\n\n"
                    f"Detailed rows exported: onus_duplicates_detail_{current_time}.tsv"
                ),
                "Repeated ON_US values can indicate deposit-slip-like patterns; review with sequence and filename context.",
            )
        else:
            log_check(
                "ON_US Duplicate Pattern Check (Deposit-Slip Lead)",
                "PASS",
                "No duplicated ON_US values detected among non-blank ON_US records.",
                "No ON_US duplication lead detected for deposit-slip investigation.",
            )

    settlement_col = "20_bundle_business_date"
    if settlement_col in df_forward.columns:
        df_settle = df_forward.copy()
        df_settle[settlement_col] = _normalize_text_series(df_settle, settlement_col)
        invalid_mask = ~df_settle[settlement_col].str.match(r"^\d{8}$")
        missing_count = invalid_mask.sum()
        valid_dates = df_settle.loc[~invalid_mask, settlement_col]
        date_counts = valid_dates.value_counts().sort_index().reset_index()
        date_counts.columns = ["Settlement_Date", "Record_Count"]
        min_date = valid_dates.min() if not valid_dates.empty else None
        max_date = valid_dates.max() if not valid_dates.empty else None
        log_check(
            "Settlement Dates Check",
            "INFO" if missing_count == 0 else "WARN",
            (
                f"Settlement date range: {min_date} to {max_date}\n\n"
                f"Record count by settlement date (Top 10):\n"
                f"{date_counts.head(10).to_string(index=False)}\n\n"
                f"Records with missing or invalid settlement date: {missing_count:,}"
            ),
            "Settlement dates are derived from bundle business dates. Review missing or malformed dates.",
        )

    if enable_sequence_check:
        df_forward["seq_num"] = pd.to_numeric(
            df_forward["25_ece_institution_item_sequence_number"], errors="coerce"
        )
        df_forward_sorted = df_forward.sort_values("seq_num").dropna(subset=["seq_num"])
        if len(df_forward_sorted) > 0:
            gaps = []
            prev_seq = None
            for seq in df_forward_sorted["seq_num"]:
                if prev_seq is not None and seq - prev_seq > 1:
                    gaps.append((int(prev_seq), int(seq)))
                prev_seq = seq
            if len(gaps) > 0:
                gap_details = "\n".join(
                    [f"Gap: {start} -> {end} (missing {end-start-1})" for start, end in gaps[:10]]
                )
                log_check(
                    "Sequence Number Continuity",
                    "WARN",
                    f"{len(gaps)} gaps found in sequence numbers\n\n{gap_details}",
                    "Sequence gaps may indicate missing records. Verify with customer.",
                )
            else:
                log_check(
                    "Sequence Number Continuity",
                    "PASS",
                    "No gaps in ECE institution item sequence numbers",
                    "No action required.",
                )

    log_summary("Data Integrity Checks")

    # ============================================================
    # SECTION 6: RETURN RECORDS VALIDATION
    # ============================================================
    if df_return.shape[0] > 0:
        log_check(
            "Return Records Summary",
            "INFO",
            f"Processing {len(df_return):,} return records",
            "Review return records for patterns indicating systemic issues.",
        )

        if (
            "31_payor_bank_routing_number" in df_return.columns
            and "31_payor_bank_routing_number_check_digit" in df_return.columns
        ):
            df_return["RETURN_PAYOR_ROUTING"] = _normalize_text_series(
                df_return, "31_payor_bank_routing_number"
            ) + _normalize_text_series(df_return, "31_payor_bank_routing_number_check_digit")

        required_fields = [
            "RETURN_PAYOR_ROUTING",
            "31_on_us_return_record",
            "32_bofd_routing_number",
            "32_deposit_account_number_at_bofd",
        ]
        existing_required = [f for f in required_fields if f in df_return.columns]
        missing_counts = {}
        normalized_return_fields = {}
        for field in existing_required:
            normalized = _normalize_text_series(df_return, field)
            normalized_return_fields[field] = normalized
            missing_counts[field] = int((normalized == "").sum())
        for field, count in missing_counts.items():
            log_check(
                f"Return Records Missing Value Check: {field}",
                "FAIL" if count > 0 else "PASS",
                f"{count:,} missing/blank values in {field}",
                "There should be no missing values. Investigate if count > 0.",
            )

        for field in existing_required:
            top_vals = normalized_return_fields[field][
                normalized_return_fields[field] != ""
            ].value_counts().head(5)
            if not top_vals.empty:
                details_df = top_vals.reset_index()
                details_df.columns = ["Value", "Count"]
                log_check(
                    f"Return Records Top Values: {field}",
                    "INFO",
                    f"\n{details_df.to_string(index=False)}",
                    "Review if these values are expected.",
                )

        if "31_return_reason" in df_return.columns:
            reason_counts = df_return["31_return_reason"].value_counts().head(10)
            if not reason_counts.empty:
                reason_df = reason_counts.reset_index()
                reason_df.columns = ["Return_Reason", "Count"]
                log_check(
                    "Return Records Return Reason Distribution",
                    "INFO",
                    f"Top return reasons:\n{reason_df.to_string(index=False)}",
                    "Review if return reasons indicate systematic issues.",
                )

        if "35_endorsing_bank_endorsement_date" in df_return.columns:
            endorsement_dates = pd.to_datetime(
                df_return["35_endorsing_bank_endorsement_date"],
                format="%Y%m%d",
                errors="coerce",
            ).dropna()
            if not endorsement_dates.empty:
                log_check(
                    "Return Records Endorsement Date Range",
                    "INFO",
                    (
                        f"Endorsement dates from {endorsement_dates.min().date()} "
                        f"to {endorsement_dates.max().date()}"
                    ),
                    "Ensure dates align with data collection period.",
                )

    log_summary("Return Records Validation")
    log_individual_check_results()
    log_footer(check_results["FAIL"], check_results["WARN"])
    log_section_end("SECTION 1 X937 RDV VALIDATION TEST")
    print("\nX937 validation completed.")
