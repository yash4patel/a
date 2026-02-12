import codecs
import glob
import json
import os
import re
from datetime import datetime, timedelta
from typing import Dict, List

import chardet
import pandas as pd

from log_manager import check_results, log_check, log_footer, log_header, log_summary

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
REQUIRED_RECORD_TYPES = ("25", "26", "50", "52")
MAX_ISSUES_PER_FILE = 100

# (field_name, start, end, validation_type, expected_length)
# validation_type values:
# - "digits": required numeric with expected_length
# - "non_empty": required non-blank
CRITICAL_FIELD_RULES = {
    "25": [
        ("payor_bank_routing_number", 19, 27, "digits", 8),
        ("payor_bank_routing_number_check_digit", 27, 28, "digits", 1),
        ("on_us", 28, 48, "non_empty", None),
        ("item_amount", 48, 58, "digits", 10),
    ],
    "26": [
        ("bofd_routing_number", 4, 13, "digits", 9),
        ("deposit_account_number_at_bofd", 36, 54, "non_empty", None),
    ],
    "50": [
        ("cash_letter_item_count", 3, 11, "digits", 8),
        ("cash_letter_amount_total", 11, 23, "digits", 12),
    ],
    "52": [
        ("bundle_item_count", 3, 11, "digits", 8),
        ("bundle_amount_total", 11, 23, "digits", 12),
    ],
}


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


def validate_critical_fields_for_record(line: str, record_type: str, line_number: int):
    """Validate critical field presence and basic format on selected record types."""
    issues = []
    for field_name, start, end, validation_type, expected_len in CRITICAL_FIELD_RULES.get(record_type, []):
        value = ""
        if len(line) >= end:
            value = line[start:end].strip()
        elif len(line) > start:
            value = line[start:].strip()

        if validation_type == "non_empty":
            if not value:
                issues.append(
                    f"Record {record_type} line {line_number}: missing required field {field_name}"
                )
        elif validation_type == "digits":
            if not value:
                issues.append(
                    f"Record {record_type} line {line_number}: missing required field {field_name}"
                )
            elif not value.isdigit():
                issues.append(
                    f"Record {record_type} line {line_number}: field {field_name} must be numeric, got '{value}'"
                )
            elif expected_len is not None and len(value) != expected_len:
                issues.append(
                    f"Record {record_type} line {line_number}: field {field_name} must be "
                    f"{expected_len} digits, got {len(value)}"
                )
    return issues


def validate_x937_file_structure(records: List[str], file_name: str) -> Dict:
    """
    Validate core X9 file structure based on meeting notes:
    1) File must begin with 01 -> 10 -> 20.
    2) Record 26 must always be preceded by record 25.
    3) Every record 25 must have at least one record 26 before next 25/31/trailer/header.
    4) Required record types 25/26/50/52 must be present.
    5) Critical fields on 25/26/50/52 must be populated and correctly formatted.
    """
    issues = []
    header_ok = False
    orphan_26_count = 0
    missing_26_after_25_count = 0
    rec25_total = 0
    rec26_total = 0
    record_type_counts = {rt: 0 for rt in REQUIRED_RECORD_TYPES}
    critical_field_error_count = 0
    dropped_issue_count = 0

    def add_issue(message: str):
        nonlocal dropped_issue_count
        if len(issues) < MAX_ISSUES_PER_FILE:
            issues.append(message)
        else:
            dropped_issue_count += 1

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
        if rt in record_type_counts:
            record_type_counts[rt] += 1
            critical_field_issues = validate_critical_fields_for_record(line, rt, idx)
            critical_field_error_count += len(critical_field_issues)
            for msg in critical_field_issues:
                add_issue(msg)

        if rt == "25":
            rec25_total += 1
            if open_25_line is not None and not open_25_has_26:
                missing_26_after_25_count += 1
                add_issue(
                    f"Record 25 at line {open_25_line} has no corresponding 26 before next 25"
                )
            open_25_line = idx
            open_25_has_26 = False
        elif rt == "26":
            rec26_total += 1
            if open_25_line is None:
                orphan_26_count += 1
                add_issue(f"Record 26 at line {idx} is not preceded by record 25")
            else:
                open_25_has_26 = True
        elif rt in close_25_context:
            if open_25_line is not None and not open_25_has_26:
                missing_26_after_25_count += 1
                add_issue(
                    f"Record 25 at line {open_25_line} has no corresponding 26 before record {rt} at line {idx}"
                )
            open_25_line = None
            open_25_has_26 = False

    if open_25_line is not None and not open_25_has_26:
        missing_26_after_25_count += 1
        add_issue(f"Record 25 at line {open_25_line} has no corresponding 26 before end of file")

    missing_required_record_types = [rt for rt, count in record_type_counts.items() if count == 0]
    if missing_required_record_types:
        add_issue(
            "Missing required record types: " + ", ".join(missing_required_record_types)
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
        ),
        "header_ok": header_ok,
        "orphan_26_count": orphan_26_count,
        "missing_26_after_25_count": missing_26_after_25_count,
        "missing_required_record_types": missing_required_record_types,
        "critical_field_error_count": critical_field_error_count,
        "record_type_counts": record_type_counts,
        "record_25_count": rec25_total,
        "record_26_count": rec26_total,
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

                while line and get_record_type(line) != "25" and current_index < len(lines):
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

                while line and get_record_type(line) != "31" and current_index < len(lines):
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
    """Classify transaction based on payor and BOFD routing numbers."""
    try:
        payor = str(row.get("25_payor_bank_routing_number", "")).strip() + str(
            row.get("25_payor_bank_routing_number_check_digit", "")
        ).strip()
        bofd = str(row.get("26_bofd_routing_number", "")).strip()
        payor_is_ours = payor in our_aba_list
        bofd_is_ours = bofd in our_aba_list
        if payor_is_ours and bofd_is_ours:
            return "ON_US"
        if payor_is_ours and not bofd_is_ours:
            return "WITHDRAWAL"
        if not payor_is_ours and bofd_is_ours:
            return "DEPOSIT"
        return "TRANSIT"
    except Exception:
        return "UNKNOWN"


def credit_debit_flag(row, our_aba_list):
    """Determine credit/debit flag based on routing numbers."""
    try:
        if row.get("BOFD_ROUTING") in our_aba_list:
            return "CREDIT"
        if row.get("PAYOR_ROUTING") in our_aba_list:
            return "DEBIT"
        return "TRANSIT"
    except Exception:
        return "UNKNOWN"


def top_10(df):
    """Get top 10 transactions by on_us, payor routing, and bofd routing."""
    if df.empty:
        return pd.DataFrame()
    return (
        df.groupby(["25_on_us", "PAYOR_ROUTING", "BOFD_ROUTING"])
        .size()
        .reset_index(name="COUNT")
        .sort_values("COUNT", ascending=False)
        .head(10)
    )


def weekdays_between_dates(start_date, end_date):
    """Get list of weekdays between two dates."""
    weekdays = []
    current_date = start_date
    while current_date <= end_date:
        if current_date.weekday() < 5:
            weekdays.append(current_date)
        current_date += timedelta(days=1)
    return weekdays


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
    valid_types = [
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
        "61",
        "62",
        "70",
        "90",
        "99",
    ]
    if record_type not in valid_types:
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
        file_names = [os.path.basename(f) for f in x9_files]
        dates = sorted({re.findall(r"\d{8}", f)[0] for f in file_names if re.findall(r"\d{8}", f)})
        if dates:
            sample_dates = dates[:sample_days]
            x9_files = [
                f
                for f in x9_files
                if re.findall(r"\d{8}", os.path.basename(f))
                and re.findall(r"\d{8}", os.path.basename(f))[0] in sample_dates
            ]
            print(f"Sampling: {sample_days} days\n")

    file_count = len(x9_files)
    if file_count == 0:
        print("ERROR: No files to process")
        return

    print(f"Configuration: OUR_ABA_LIST={our_aba_list}, Files={file_count}\n")

    # ============================================================
    # PRE-SCAN: syntax and structure validation per file
    # ============================================================
    valid_x9_files = []
    invalid_file_rows = []
    structure_results = []
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
            invalid_file_rows.append(
                {
                    "filename": os.path.basename(path),
                    "status": "INVALID",
                    "syntax_errors": 0,
                    "header_ok": False,
                    "orphan_26_count": 0,
                    "missing_26_after_25_count": 0,
                    "missing_required_record_types": ",".join(REQUIRED_RECORD_TYPES),
                    "critical_field_error_count": 0,
                    "issues": f"Unable to read file: {e}",
                }
            )
            continue

        structure = validate_x937_file_structure(records, os.path.basename(path))
        structure_results.append(structure)
        has_structure_errors = not structure["is_valid"]
        if syntax_errors == 0 and not has_structure_errors:
            valid_x9_files.append(path)
        else:
            issues = list(structure["issues"])
            if syntax_errors > 0:
                issues.insert(0, f"Syntax errors: {syntax_errors}")
            invalid_file_rows.append(
                {
                    "filename": os.path.basename(path),
                    "status": "INVALID",
                    "syntax_errors": syntax_errors,
                    "header_ok": structure["header_ok"],
                    "orphan_26_count": structure["orphan_26_count"],
                    "missing_26_after_25_count": structure["missing_26_after_25_count"],
                    "missing_required_record_types": ",".join(structure["missing_required_record_types"]),
                    "critical_field_error_count": structure["critical_field_error_count"],
                    "issues": " | ".join(issues) if issues else "Unknown validation issue",
                }
            )

    invalid_structure_report = None
    if invalid_file_rows:
        invalid_structure_report = f"invalid_x937_structure_{current_time}.tsv"
        pd.DataFrame(invalid_file_rows).to_csv(invalid_structure_report, sep="\t", index=False)

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

    if df_all_forward.empty:
        df_forward = pd.DataFrame()
    else:
        if "25_item_amount" in df_all_forward.columns:
            df_forward = df_all_forward[df_all_forward["25_item_amount"].notna()].copy()
        else:
            df_forward = pd.DataFrame()

    print(f"Forward: {len(df_forward):,}, Return: {len(df_return):,}\n")

    if not df_forward.empty:
        df_forward.to_csv(f"forward_result_{current_time}.tsv", sep="\t", index=False)
    if not df_return.empty:
        df_return.to_csv(f"return_result_{current_time}.tsv", sep="\t", index=False)

    # ============================================================
    # SECTION 1: FILE & DATA QUALITY
    # ============================================================
    log_header("X9 Check Validation Report", file_count)

    # 1.1 Data Continuity
    if enable_date_continuity:
        file_names = [os.path.basename(f) for f in x9_files]
        dates = sorted({re.findall(r"\d{8}", f)[0] for f in file_names if re.findall(r"\d{8}", f)})
        if dates and len(dates) > 1:
            start_date = datetime.strptime(dates[0], "%Y%m%d")
            end_date = datetime.strptime(dates[-1], "%Y%m%d")
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

    # 1.2 Bad Record Check (unified threshold rule)
    bad_record_perc = round((bad_record_cnt / total_record_cnt) * 100, 2) if total_record_cnt else 0
    status = "FAIL" if bad_record_perc > bad_record_threshold else "PASS"
    log_check(
        "Bad Record Check",
        status,
        (
            f"Total records scanned: {total_record_cnt:,}\n"
            f"Bad records found: {bad_record_cnt:,}\n"
            f"Bad record percentage: {bad_record_perc}%\n"
            f"Configured threshold: {bad_record_threshold}%"
        ),
        "FAIL if bad record percentage exceeds threshold.",
    )

    # 1.3 Structural Record Order Check from meeting notes
    header_fail_files = sum(1 for r in structure_results if not r["header_ok"])
    orphan_26_total = sum(r["orphan_26_count"] for r in structure_results)
    missing_26_total = sum(r["missing_26_after_25_count"] for r in structure_results)
    files_missing_required = sum(1 for r in structure_results if r["missing_required_record_types"])
    files_with_critical_field_errors = sum(1 for r in structure_results if r["critical_field_error_count"] > 0)
    critical_field_error_total = sum(r["critical_field_error_count"] for r in structure_results)
    required_record_type_totals = {
        rt: sum(r["record_type_counts"].get(rt, 0) for r in structure_results)
        for rt in REQUIRED_RECORD_TYPES
    }
    invalid_files_count = len(invalid_file_rows)

    structure_status = "PASS" if invalid_files_count == 0 else "FAIL"
    detail_lines = [
        f"Files scanned: {file_count:,}",
        f"Valid files: {len(valid_x9_files):,}",
        f"Invalid files: {invalid_files_count:,}",
        f"Files failing 01->10->20 header sequence: {header_fail_files:,}",
        f"Orphan 26 records (26 without preceding 25): {orphan_26_total:,}",
        f"25 records missing corresponding 26: {missing_26_total:,}",
        (
            "Required record totals: "
            + ", ".join([f"{rt}={required_record_type_totals[rt]:,}" for rt in REQUIRED_RECORD_TYPES])
        ),
        f"Files missing one or more required record types (25/26/50/52): {files_missing_required:,}",
        f"Files with critical field issues on 25/26/50/52: {files_with_critical_field_errors:,}",
        f"Total critical field issues: {critical_field_error_total:,}",
    ]
    if invalid_structure_report:
        detail_lines.append(f"Invalid file report: {invalid_structure_report}")
    if invalid_file_rows:
        examples = invalid_file_rows[:5]
        preview = "\n".join([f" - {r['filename']}: {r['issues']}" for r in examples])
        detail_lines.append(f"Sample issues:\n{preview}")

    log_check(
        "Record Structure Check (Header + 25/26 Ordering)",
        structure_status,
        "\n".join(detail_lines),
        "X9 file must start with 01->10->20, each 26 must follow 25, and each 25 must include at least one 26.",
    )

    required_record_status = "PASS" if files_missing_required == 0 else "FAIL"
    required_examples = [
        f"{r['file']}: missing {','.join(r['missing_required_record_types'])}"
        for r in structure_results
        if r["missing_required_record_types"]
    ][:10]
    required_details = [
        "File-level required record type presence (25/26/50/52)",
        (
            "Totals across scanned files: "
            + ", ".join([f"{rt}={required_record_type_totals[rt]:,}" for rt in REQUIRED_RECORD_TYPES])
        ),
        f"Files missing required record types: {files_missing_required:,}",
    ]
    if required_examples:
        required_details.append("Examples:\n - " + "\n - ".join(required_examples))
    log_check(
        "Basic Validation: Required Record Types (25/26/50/52)",
        required_record_status,
        "\n".join(required_details),
        "Each file must contain record types 25, 26, 50, and 52.",
    )

    critical_status = "PASS" if critical_field_error_total == 0 else "FAIL"
    critical_examples = []
    for result in structure_results:
        if result["critical_field_error_count"] > 0 and result["issues"]:
            # Pick first issue from this file that references critical fields.
            first_match = next(
                (
                    issue
                    for issue in result["issues"]
                    if "missing required field" in issue
                    or "must be numeric" in issue
                    or "must be " in issue
                ),
                "",
            )
            if first_match:
                critical_examples.append(f"{result['file']}: {first_match}")
        if len(critical_examples) >= 10:
            break
    critical_details = [
        "Critical fields validated on record types 25/26/50/52.",
        "Fields include routing/account identifiers and control totals.",
        f"Files with critical field issues: {files_with_critical_field_errors:,}",
        f"Total critical field issues: {critical_field_error_total:,}",
    ]
    if critical_examples:
        critical_details.append("Examples:\n - " + "\n - ".join(critical_examples))
    log_check(
        "Basic Validation: Critical Fields Presence (25/26/50/52)",
        critical_status,
        "\n".join(critical_details),
        "Critical fields (e.g., ABA/routing and account/control fields) must be populated and valid.",
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

    if df_forward.empty:
        log_check(
            "Forward Record Availability",
            "FAIL",
            "No valid forward records available after structure and syntax validation.",
            "Review invalid_x937_structure report and source files.",
        )
        log_summary("Processing Availability")
        log_footer(check_results["FAIL"], check_results["WARN"])
        print("\nX937 validation completed with critical issues.")
        return

    # ============================================================
    # SECTION 2: TRANSACTION CLASSIFICATION & DISTRIBUTION
    # ============================================================
    df_forward["TRANSACTION_TYPE"] = df_forward.apply(lambda row: classify_transaction(row, our_aba_list), axis=1)
    df_forward["VALID_ROUTING"] = (
        df_forward["25_payor_bank_routing_number"].astype(str).str.len().eq(8)
        & df_forward["25_payor_bank_routing_number_check_digit"].astype(str).str.len().eq(1)
        & df_forward["26_bofd_routing_number"].astype(str).str.len().eq(9)
    )
    df_forward["PAYOR_ROUTING"] = (
        df_forward["25_payor_bank_routing_number"].astype(str)
        + df_forward["25_payor_bank_routing_number_check_digit"].astype(str)
    )
    df_forward["BOFD_ROUTING"] = df_forward["26_bofd_routing_number"].astype(str)
    df_forward["CR_DR_FLAG"] = df_forward.apply(lambda row: credit_debit_flag(row, our_aba_list), axis=1)
    df_forward["ITEM_AMOUNT_FLOAT"] = pd.to_numeric(df_forward["25_item_amount"], errors="coerce") / 100
    df_forward["onus_elements"] = (
        df_forward["25_on_us"].astype(str).str.strip().str.strip("/").str.split("/").apply(len)
    )

    withdrawals = df_forward[df_forward["TRANSACTION_TYPE"] == "WITHDRAWAL"]
    deposits = df_forward[df_forward["TRANSACTION_TYPE"] == "DEPOSIT"]
    on_us = df_forward[df_forward["TRANSACTION_TYPE"] == "ON_US"]
    transit = df_forward[df_forward["TRANSACTION_TYPE"] == "TRANSIT"]
    total = len(df_forward)

    log_check(
        "Transaction Type Distribution",
        "INFO",
        (
            f"Withdrawals: {len(withdrawals):,} ({round(len(withdrawals)/total*100,2) if total else 0}%)\n"
            f"Deposits: {len(deposits):,} ({round(len(deposits)/total*100,2) if total else 0}%)\n"
            f"ON_US: {len(on_us):,} ({round(len(on_us)/total*100,2) if total else 0}%)\n"
            f"TRANSIT: {len(transit):,} ({round(len(transit)/total*100,2) if total else 0}%)\n"
            f"TOTAL: {total:,}"
        ),
        "Review transaction distribution for expected patterns.",
    )

    credit_count = (df_forward["CR_DR_FLAG"] == "CREDIT").sum()
    debit_count = (df_forward["CR_DR_FLAG"] == "DEBIT").sum()
    transit_count = (df_forward["CR_DR_FLAG"] == "TRANSIT").sum()
    unknown_count = (df_forward["CR_DR_FLAG"] == "UNKNOWN").sum()
    log_check(
        "Credit/Debit Distribution",
        "INFO",
        (
            f"CREDIT records: {credit_count:,}\n"
            f"DEBIT records: {debit_count:,}\n"
            f"TRANSIT records: {transit_count:,}\n"
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
    # SECTION 3: AMOUNT VALIDATION
    # ============================================================
    amount_stats = df_forward["ITEM_AMOUNT_FLOAT"].describe()
    log_check(
        "Amount Distribution Statistics",
        "INFO",
        (
            f"Count: {int(amount_stats['count']):,}\n"
            f"Mean: ${amount_stats['mean']:.2f}\n"
            f"Median: ${df_forward['ITEM_AMOUNT_FLOAT'].median():.2f}\n"
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

    aux_populated = df_forward[df_forward["25_auxiliary_on_us"].astype(str).str.strip() != ""]
    aux_percentage = round(len(aux_populated) / len(df_forward) * 100, 2) if len(df_forward) else 0
    log_check(
        "Auxiliary ON_US Population",
        "INFO",
        f"{len(aux_populated):,} records ({aux_percentage}%) have Auxiliary ON_US populated",
        "Review if auxiliary ON_US usage aligns with expected check numbering conventions.",
    )

    log_summary("Field Structure Validation")

    # ============================================================
    # SECTION 5: DATA INTEGRITY CHECKS
    # ============================================================
    if enable_duplicate_check:
        df_forward["25_on_us"] = df_forward["25_on_us"].astype(str).str.strip().str.strip("/")
        df_forward["25_auxiliary_on_us"] = df_forward["25_auxiliary_on_us"].astype(str).str.strip()
        df_forward["payer_account"] = df_forward["25_on_us"].str.split("/").str[0]
        aux_on_us = df_forward["25_auxiliary_on_us"].replace("", None)
        on_us_last = df_forward["25_on_us"].str.split("/").str[-1]
        df_forward["check_number"] = aux_on_us.fillna(on_us_last)

        null_cnt = df_forward["payer_account"].isna().sum()
        duplicate_key = ["payer_account", "check_number"]
        is_duplicated = df_forward.duplicated(subset=duplicate_key, keep=False)
        df_duplicates = df_forward[is_duplicated].copy()

        if not df_duplicates.empty:
            df_checknum_counts = df_duplicates.groupby(duplicate_key).size().reset_index(name="count")
            df_checknum_counts = df_checknum_counts.sort_values(by="count", ascending=False)
            threshold = 10
            high_volume_duplicates = df_checknum_counts[df_checknum_counts["count"] > threshold]
            log_check(
                "Duplicate Check Number Check (payer_account + check_number)",
                "WARN",
                (
                    f"Null payer accounts: {null_cnt}\n"
                    f"Total duplicate records: {len(df_duplicates):,}\n"
                    f"Unique duplicate check combinations: {len(df_checknum_counts):,}\n\n"
                    f"Top 20 duplicate checks:\n"
                    f"{df_checknum_counts.head(20).to_string(index=False)}\n\n"
                    f"High volume duplicates (count > {threshold}): {len(high_volume_duplicates)}\n"
                    f"{high_volume_duplicates.to_string(index=False) if not high_volume_duplicates.empty else 'None'}"
                ),
                "Duplicate checks identified. High volume duplicates may indicate systematic issues.",
            )

            tracking_fields = [
                "payer_account",
                "check_number",
                "filename",
                "25_ece_institution_item_sequence_number",
                "25_item_amount",
                "20_bundle_business_date",
            ]
            df_duplicates[tracking_fields].to_csv(
                f"duplicate_checks_detail_{current_time}.tsv",
                sep="\t",
                index=False,
            )
        else:
            log_check(
                "Duplicate Check Number Check (payer_account + check_number)",
                "PASS",
                "No duplicate checks found.",
                "No action required.",
            )

    settlement_col = "20_bundle_business_date"
    if settlement_col in df_forward.columns:
        df_settle = df_forward.copy()
        df_settle[settlement_col] = df_settle[settlement_col].astype(str).str.strip()
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

        if "31_payor_bank_routing_number" in df_return.columns and "31_payor_bank_routing_number_check_digit" in df_return.columns:
            df_return["RETURN_PAYOR_ROUTING"] = (
                df_return["31_payor_bank_routing_number"].astype(str)
                + df_return["31_payor_bank_routing_number_check_digit"].astype(str)
            )

        required_fields = [
            "RETURN_PAYOR_ROUTING",
            "31_on_us_return_record",
            "32_bofd_routing_number",
            "32_deposit_account_number_at_bofd",
        ]
        existing_required = [f for f in required_fields if f in df_return.columns]
        na_counts = df_return[existing_required].isnull().sum()
        for field, count in na_counts.items():
            log_check(
                f"Return Records Missing Value Check: {field}",
                "FAIL" if count > 0 else "PASS",
                f"{count:,} missing values in {field}",
                "There should be no missing values. Investigate if count > 0.",
            )

        for field in existing_required:
            top_vals = df_return[field].value_counts().head(5)
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
    log_footer(check_results["FAIL"], check_results["WARN"])
    print("\nX937 validation completed.")
