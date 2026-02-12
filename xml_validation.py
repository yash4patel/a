import os
import re
from datetime import datetime, timedelta

import pandas as pd
import warnings

from log_manager import check_results, log_check, log_footer, log_header, log_summary
from xml_standard import Standard

warnings.filterwarnings("ignore")

# Field Definitions
PAYOR_ABA_FIELD = (
    "/X937CHECK/FILE_HEADER_RECORD/CASH_LETTER_HEADER_RECORD/BUNDLE_HEADER_RECORD/"
    "CHECK_DETAIL_RECORD/PAYOR_BANK_ROUTING_NUMBER"
)
PAYOR_CHECK_DIGIT_FIELD = (
    "/X937CHECK/FILE_HEADER_RECORD/CASH_LETTER_HEADER_RECORD/BUNDLE_HEADER_RECORD/"
    "CHECK_DETAIL_RECORD/PAYOR_BANK_ROUTING_NUMBER_CHECK_DIGIT"
)
BOFD_ROUTING_FIELD = (
    "/X937CHECK/FILE_HEADER_RECORD/CASH_LETTER_HEADER_RECORD/BUNDLE_HEADER_RECORD/"
    "CHECK_DETAIL_ADDENDUM_A_RECORD/BANK_OF_FIRST_DEPOSIT_ROUTING_NUMBER"
)
ITEM_AMOUNT_FIELD = (
    "/X937CHECK/FILE_HEADER_RECORD/CASH_LETTER_HEADER_RECORD/BUNDLE_HEADER_RECORD/"
    "CHECK_DETAIL_RECORD/ITEM_AMOUNT"
)
ON_US_FIELD = (
    "/X937CHECK/FILE_HEADER_RECORD/CASH_LETTER_HEADER_RECORD/BUNDLE_HEADER_RECORD/"
    "CHECK_DETAIL_RECORD/ON_US"
)
AUX_ON_US_FIELD = (
    "/X937CHECK/FILE_HEADER_RECORD/CASH_LETTER_HEADER_RECORD/BUNDLE_HEADER_RECORD/"
    "CHECK_DETAIL_RECORD/AUXILIARY_ON_US"
)
COLLECTION_TYPE_FIELD = "/X937CHECK/FILE_HEADER_RECORD/CASH_LETTER_HEADER_RECORD/COLLECTION_TYPE_INDICATOR"
BUNDLE_DATE_FIELD = (
    "/X937CHECK/FILE_HEADER_RECORD/CASH_LETTER_HEADER_RECORD/BUNDLE_HEADER_RECORD/BUNDLE_BUSINESS_DATE"
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


def top_10(df, payor_col="PAYOR_ROUTING", bofd_col="BOFD_ROUTING", onus_col=ON_US_FIELD):
    """Get top 10 transactions by routing and on_us combination."""
    if df.empty or onus_col not in df.columns:
        return pd.DataFrame()
    return (
        df.groupby([payor_col, bofd_col, onus_col])
        .size()
        .reset_index(name="COUNT")
        .sort_values("COUNT", ascending=False)
        .head(10)
    )


def run_xml_validation(config):
    """Run XML validation with configuration from config.ini."""
    path = config.get("DATA", "input_path")
    sample_days_count = config.getint("DATA", "sample_days")
    bad_record_threshold = config.getfloat("VALIDATION", "bad_record_threshold")
    allow_zero = config.getboolean("VALIDATION", "allow_zero_amount")
    allow_missing = config.getboolean("VALIDATION", "allow_missing_amount")
    onus_max = config.getint("VALIDATION", "onus_max_elements")
    our_aba_raw = config.get("X937", "our_aba")
    our_aba_list = [aba.strip() for aba in our_aba_raw.split(",") if aba.strip()]
    enable_date_continuity = config.getboolean("VALIDATION", "enable_date_continuity", fallback=True)

    try:
        enable_outlier_detection = config.getboolean("VALIDATION", "enable_outlier_detection")
        iqr_multiplier = config.getfloat("VALIDATION", "iqr_multiplier")
        enable_duplicate_check = config.getboolean("VALIDATION", "enable_duplicate_check")
    except Exception:
        enable_outlier_detection, iqr_multiplier, enable_duplicate_check = True, 3.0, True

    current_time = datetime.now().strftime("%Y%m%d")

    print(f"\nConfiguration: Input={path}, Sample days={sample_days_count}, Our ABA={our_aba_list}\n")

    file_names = []
    all_files = []
    for root, _, files in os.walk(path):
        for file in files:
            if file.endswith(".xml"):
                file_names.append(file)
                all_files.append(os.path.join(root, file))

    if not all_files:
        print(f"ERROR: No XML files found in {path}")
        return

    file_names.sort()
    all_files.sort()
    print(f"First: {file_names[0]}, Last: {file_names[-1]}, Count: {len(all_files)}\n")

    dates = ["".join(re.findall(r"\d", f))[:8] for f in file_names]
    unique_dates = sorted(set(dates))

    # ============================================================
    # SECTION 1: FILE & DATA QUALITY
    # ============================================================
    log_header("XML Dataset Validation", len(all_files))

    if enable_date_continuity:
        try:
            start_date = datetime.strptime(re.findall(r"\d{8}", file_names[0])[0], "%Y%m%d")
            end_date = datetime.strptime(re.findall(r"\d{8}", file_names[-1])[0], "%Y%m%d")
            required_days = [d.strftime("%Y%m%d") for d in weekdays_between_dates(start_date, end_date)]
            missing = set(required_days) - set(dates)
            if missing:
                log_check(
                    "Data Continuity Check",
                    "WARN",
                    f"Missing dates: {sorted(missing)}",
                    "Verify if these dates are holidays; otherwise check with customer.",
                )
            else:
                log_check(
                    "Data Continuity Check",
                    "PASS",
                    "Data is continuous.",
                    "No action required.",
                )
        except Exception:
            log_check(
                "Data Continuity Check",
                "INFO",
                "Unable to infer dates from file names.",
                "Informational only.",
            )
    else:
        log_check(
            "Data Continuity Check",
            "INFO",
            "Skipped by configuration (enable_date_continuity=false).",
            "Enable date continuity if date-gap monitoring is required.",
        )

    sample_days = unique_dates[:sample_days_count] if sample_days_count > 0 else unique_dates
    sample_files = [f for f, d in zip(all_files, dates) if d in sample_days]
    print(f"Selected days: {sample_days}, Files: {len(sample_files)}\n")

    print("Reading XML files...\n")
    bad_record_cnt = 0
    overall_cnt = 0
    pathspecs = []
    for file_path in sample_files:
        with open(file_path, "r") as fp:
            for line in fp:
                try:
                    pathspecs.append(Standard(line).to_dict())
                    overall_cnt += 1
                except Exception:
                    bad_record_cnt += 1

    bad_perc = round((bad_record_cnt / overall_cnt) * 100, 2) if overall_cnt else 0
    status = "FAIL" if bad_perc > bad_record_threshold else "PASS"
    log_check(
        "Bad Record Check",
        status,
        (
            f"Total records scanned: {overall_cnt:,}\n"
            f"Bad records found: {bad_record_cnt:,}\n"
            f"Bad record percentage: {bad_perc}%"
        ),
        f"FAIL indicates structurally invalid XML records. Threshold: {bad_record_threshold}%",
    )

    df = pd.DataFrame(pathspecs)
    print(f"Total records parsed: {len(df)}\n")

    if df.empty:
        log_check(
            "Parsed Record Availability",
            "FAIL",
            "No XML records parsed successfully.",
            "Validate source XML structure and parser assumptions.",
        )
        log_summary("File & Data Quality")
        log_footer(check_results["FAIL"], check_results["WARN"])
        return

    df_62 = df.filter(regex="62").dropna(how="all")
    if COLLECTION_TYPE_FIELD in df.columns:
        df_return = df[df[COLLECTION_TYPE_FIELD] == "03"]
    else:
        df_return = pd.DataFrame()

    df_legit = df.drop(df_62.index, errors="ignore")
    df_legit = df_legit.drop(df_return.index, errors="ignore")
    df_legit.dropna(axis=1, how="all", inplace=True)

    log_check("Credit Records Check (RT 62)", "INFO", f"Count = {df_62.shape[0]:,}", "Informational only.")
    log_check("Return Records Count", "INFO", f"Count = {df_return.shape[0]:,}", "Review if returns look normal.")
    log_check(
        "Legit/Forward Records",
        "INFO",
        f"Count = {df_legit.shape[0]:,}",
        "Used for further validation.",
    )

    if df_legit.empty:
        print("ERROR: No legit records")
        log_footer(check_results["FAIL"], check_results["WARN"])
        return

    log_summary("File & Data Quality")

    if ITEM_AMOUNT_FIELD in df_legit.columns:
        df_legit["ITEM_AMOUNT"] = pd.to_numeric(df_legit[ITEM_AMOUNT_FIELD], errors="coerce") / 100

    if ON_US_FIELD in df_legit.columns:
        df_legit["ONUS_list"] = df_legit[ON_US_FIELD].astype(str).str.strip().str.strip("/").str.split("/")
        df_legit["ONUS_element_count"] = df_legit["ONUS_list"].apply(
            lambda x: len(x) if isinstance(x, list) else 0
        )

    has_all_fields = all(
        [
            PAYOR_ABA_FIELD in df_legit.columns,
            PAYOR_CHECK_DIGIT_FIELD in df_legit.columns,
            BOFD_ROUTING_FIELD in df_legit.columns,
        ]
    )
    if not has_all_fields:
        print("Missing routing fields - cannot classify transactions")
        log_footer(check_results["FAIL"], check_results["WARN"])
        return

    df_legit["PAYOR_ROUTING"] = df_legit[PAYOR_ABA_FIELD].astype(str) + df_legit[PAYOR_CHECK_DIGIT_FIELD].astype(
        str
    )
    df_legit["BOFD_ROUTING"] = df_legit[BOFD_ROUTING_FIELD].astype(str)

    def classify_transaction(row):
        try:
            payor = row["PAYOR_ROUTING"]
            bofd = row["BOFD_ROUTING"]
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

    def credit_debit_flag(row):
        try:
            if row.get("BOFD_ROUTING") in our_aba_list:
                return "CREDIT"
            if row.get("PAYOR_ROUTING") in our_aba_list:
                return "DEBIT"
            return "TRANSIT"
        except Exception:
            return "UNKNOWN"

    df_legit["TRANSACTION_TYPE"] = df_legit.apply(classify_transaction, axis=1)
    df_legit["CR_DR_FLAG"] = df_legit.apply(credit_debit_flag, axis=1)

    type_counts = df_legit["TRANSACTION_TYPE"].value_counts()
    total = len(df_legit)

    withdrawals = df_legit[df_legit["TRANSACTION_TYPE"] == "WITHDRAWAL"]
    deposits = df_legit[df_legit["TRANSACTION_TYPE"] == "DEPOSIT"]
    on_us = df_legit[df_legit["TRANSACTION_TYPE"] == "ON_US"]
    transit = df_legit[df_legit["TRANSACTION_TYPE"] == "TRANSIT"]

    # ============================================================
    # SECTION 2: TRANSACTION CLASSIFICATION & DISTRIBUTION
    # ============================================================
    type_details = []
    for txn_type in ["WITHDRAWAL", "DEPOSIT", "ON_US", "TRANSIT", "UNKNOWN"]:
        count = type_counts.get(txn_type, 0)
        pct = round(count / total * 100, 2) if total > 0 else 0
        type_details.append(f"{txn_type}: {count:,} ({pct}%)")
    log_check(
        "Transaction Type Distribution",
        "INFO",
        "\n".join(type_details) + f"\nTOTAL: {total:,}",
        "Review transaction distribution for expected patterns.",
    )

    credit_count = (df_legit["CR_DR_FLAG"] == "CREDIT").sum()
    debit_count = (df_legit["CR_DR_FLAG"] == "DEBIT").sum()
    transit_count = (df_legit["CR_DR_FLAG"] == "TRANSIT").sum()
    unknown_count = (df_legit["CR_DR_FLAG"] == "UNKNOWN").sum()
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

    for txn_type, df_type, label in [
        ("WITHDRAWAL", withdrawals, "Withdrawals"),
        ("DEPOSIT", deposits, "Deposits"),
        ("ON_US", on_us, "ON_US Transactions"),
    ]:
        if len(df_type) > 0:
            top_10_df = top_10(df_type)
            if not top_10_df.empty:
                log_check(
                    f"Top 10 {label}",
                    "INFO",
                    f"\n{top_10_df.to_string(index=False)}",
                    f"Review high-volume {txn_type.lower()} patterns.",
                )

    df_legit["PAYOR_ROUTING_LEN"] = df_legit["PAYOR_ROUTING"].astype(str).str.len()
    df_legit["BOFD_ROUTING_LEN"] = df_legit["BOFD_ROUTING"].astype(str).str.len()
    invalid_routing = df_legit[
        (df_legit["PAYOR_ROUTING_LEN"] != 9) | (df_legit["BOFD_ROUTING_LEN"] != 9)
    ]
    invalid_routing_pct = round(len(invalid_routing) / len(df_legit) * 100, 2) if len(df_legit) > 0 else 0
    log_check(
        "Routing Number Format Validation",
        "PASS" if len(invalid_routing) == 0 else "WARN",
        (
            f"Total records: {len(df_legit):,}\n"
            f"Records with invalid routing numbers: {len(invalid_routing):,}\n"
            f"Invalid routing percentage: {invalid_routing_pct}%"
        ),
        "Payor routing should be 9 digits, BOFD routing should be 9 digits. Review if invalid count > 0.",
    )

    log_summary("Transaction Classification & Distribution")

    # ============================================================
    # SECTION 3: AMOUNT VALIDATION
    # ============================================================
    if ITEM_AMOUNT_FIELD in df_legit.columns:
        desc = df_legit["ITEM_AMOUNT"].describe()
        log_check(
            "Amount Distribution Statistics",
            "INFO",
            (
                f"Count: {int(desc['count']):,}\n"
                f"Mean: ${desc['mean']:.2f}\n"
                f"Median: ${df_legit['ITEM_AMOUNT'].median():.2f}\n"
                f"Min: ${desc['min']:.2f}\n"
                f"Max: ${desc['max']:.2f}\n"
                f"Std Dev: ${desc['std']:.2f}"
            ),
            "Review outliers and ensure amounts align with expected transaction patterns.",
        )

        zero_amount = df_legit[df_legit["ITEM_AMOUNT"] == 0]
        zero_pct = round(len(zero_amount) / len(df_legit) * 100, 2) if len(df_legit) > 0 else 0
        status = "PASS" if len(zero_amount) == 0 else ("WARN" if not allow_zero else "INFO")
        log_check(
            "Zero Amount Check",
            status,
            f"{len(zero_amount):,} records with zero amount ({zero_pct}%)",
            (
                "Zero amounts may indicate test records or data issues. Verify with customer if count > 0."
                if not allow_zero
                else "Zero amounts are allowed per configuration."
            ),
        )

        missing_amount = df_legit[df_legit["ITEM_AMOUNT"].isna()]
        missing_pct = round(len(missing_amount) / len(df_legit) * 100, 2) if len(df_legit) > 0 else 0
        status = "PASS" if len(missing_amount) == 0 else ("FAIL" if not allow_missing else "INFO")
        log_check(
            "Missing Amount Check",
            status,
            f"{len(missing_amount):,} records with missing amount ({missing_pct}%)",
            (
                "All records must have valid amounts. Investigate source data if count > 0."
                if not allow_missing
                else "Missing amounts are allowed per configuration."
            ),
        )

        if enable_outlier_detection:
            df_amount_valid = df_legit[df_legit["ITEM_AMOUNT"].notna()]
            if len(df_amount_valid) > 0:
                q1 = df_amount_valid["ITEM_AMOUNT"].quantile(0.25)
                q3 = df_amount_valid["ITEM_AMOUNT"].quantile(0.75)
                iqr = q3 - q1
                outliers = df_amount_valid[
                    (df_amount_valid["ITEM_AMOUNT"] < q1 - iqr_multiplier * iqr)
                    | (df_amount_valid["ITEM_AMOUNT"] > q3 + iqr_multiplier * iqr)
                ]
                if len(outliers) > 0:
                    cols = (
                        [ON_US_FIELD, "PAYOR_ROUTING", "BOFD_ROUTING", "ITEM_AMOUNT"]
                        if ON_US_FIELD in outliers.columns
                        else ["PAYOR_ROUTING", "BOFD_ROUTING", "ITEM_AMOUNT"]
                    )
                    top_outliers = outliers.nlargest(10, "ITEM_AMOUNT")[cols].copy()
                    top_outliers["ITEM_AMOUNT"] = top_outliers["ITEM_AMOUNT"].apply(lambda x: f"${x:.2f}")
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
    if ON_US_FIELD in df_legit.columns:
        bad_onus = df_legit[df_legit["ONUS_element_count"] > onus_max]
        bad_onus_pct = round(len(bad_onus) / len(df_legit) * 100, 2) if len(df_legit) > 0 else 0
        log_check(
            "ON_US Field Structure Validation",
            "WARN" if len(bad_onus) > 0 else "PASS",
            f"{len(bad_onus):,} records have more than {onus_max} ON_US elements ({bad_onus_pct}%)",
            f"ON_US field should contain fewer than {onus_max} slash-separated elements.",
        )

    if AUX_ON_US_FIELD in df_legit.columns:
        aux_populated = df_legit[df_legit[AUX_ON_US_FIELD].astype(str).str.strip() != ""]
        aux_percentage = round(len(aux_populated) / len(df_legit) * 100, 2) if len(df_legit) > 0 else 0
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
    if enable_duplicate_check and ON_US_FIELD in df_legit.columns and AUX_ON_US_FIELD in df_legit.columns:
        df_legit[ON_US_FIELD] = df_legit[ON_US_FIELD].astype(str).str.strip().str.strip("/")
        df_legit[AUX_ON_US_FIELD] = df_legit[AUX_ON_US_FIELD].astype(str).str.strip()
        df_legit["payer_account"] = df_legit[ON_US_FIELD].str.split("/").str[0]
        aux_on_us = df_legit[AUX_ON_US_FIELD].replace("", None)
        on_us_last = df_legit[ON_US_FIELD].str.split("/").str[-1]
        df_legit["check_number"] = aux_on_us.fillna(on_us_last)

        df_for_dup_check = df_legit[
            (df_legit["payer_account"].astype(str).str.strip() != "")
            & (df_legit["check_number"].astype(str).str.strip() != "")
        ]
        null_cnt = df_legit["payer_account"].isna().sum()

        if len(df_for_dup_check) > 0:
            duplicates = df_for_dup_check[
                df_for_dup_check.duplicated(subset=["payer_account", "check_number"], keep=False)
            ]
            if len(duplicates) > 0:
                dup_counts = duplicates.groupby(["payer_account", "check_number"]).size().reset_index(name="count")
                dup_counts = dup_counts.sort_values("count", ascending=False)
                threshold = 10
                high_volume_duplicates = dup_counts[dup_counts["count"] > threshold]
                log_check(
                    "Duplicate Check Number Check (payer_account + check_number)",
                    "WARN",
                    (
                        f"Null payer accounts: {null_cnt}\n"
                        f"Total duplicate records: {len(duplicates):,}\n"
                        f"Unique duplicate check combinations: {len(dup_counts):,}\n\n"
                        f"Top 20 duplicate checks:\n"
                        f"{dup_counts.head(20).to_string(index=False)}\n\n"
                        f"High volume duplicates (count > {threshold}): {len(high_volume_duplicates)}\n"
                        f"{high_volume_duplicates.to_string(index=False) if not high_volume_duplicates.empty else 'None'}"
                    ),
                    "Duplicate checks identified. High volume duplicates may indicate systematic issues.",
                )

                tracking_fields = ["payer_account", "check_number"]
                if ITEM_AMOUNT_FIELD in duplicates.columns:
                    tracking_fields.append(ITEM_AMOUNT_FIELD)
                if BUNDLE_DATE_FIELD in duplicates.columns:
                    tracking_fields.append(BUNDLE_DATE_FIELD)
                duplicates[tracking_fields].to_csv(
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

    if BUNDLE_DATE_FIELD in df_legit.columns:
        df_legit["BUNDLE_DATE"] = df_legit[BUNDLE_DATE_FIELD].astype(str).str.strip()
        valid_dates = df_legit[df_legit["BUNDLE_DATE"].str.match(r"^\d{8}$", na=False)]
        if len(valid_dates) > 0:
            date_counts = valid_dates["BUNDLE_DATE"].value_counts().sort_index().reset_index()
            date_counts.columns = ["Settlement_Date", "Record_Count"]
            min_date = valid_dates["BUNDLE_DATE"].min()
            max_date = valid_dates["BUNDLE_DATE"].max()
            missing_date_count = len(df_legit) - len(valid_dates)
            status = "INFO" if missing_date_count == 0 else "WARN"
            log_check(
                "Settlement Dates Check",
                status,
                (
                    f"Settlement date range: {min_date} to {max_date}\n\n"
                    f"Record count by settlement date (Top 10):\n"
                    f"{date_counts.head(10).to_string(index=False)}\n\n"
                    f"Records with missing or invalid settlement date: {missing_date_count:,}"
                ),
                "Settlement dates are derived from bundle business dates. Review missing or malformed dates.",
            )

    log_check(
        "Sequence Number Continuity",
        "INFO",
        "N/A (XML format does not have ECE institution sequence numbers)",
        "This check applies to X937 format only.",
    )

    log_summary("Data Integrity Checks")

    # ============================================================
    # SECTION 6: RETURN RECORDS VALIDATION
    # ============================================================
    if len(df_return) > 0:
        log_check(
            "Return Records Summary",
            "INFO",
            f"Processing {len(df_return):,} return records",
            "Review return records for patterns indicating systemic issues.",
        )

        return_payor_field = (
            "/X937CHECK/FILE_HEADER_RECORD/CASH_LETTER_HEADER_RECORD/BUNDLE_HEADER_RECORD/"
            "RETURN_RECORD/PAYOR_BANK_ROUTING_NUMBER"
        )
        return_payor_check_digit_field = (
            "/X937CHECK/FILE_HEADER_RECORD/CASH_LETTER_HEADER_RECORD/BUNDLE_HEADER_RECORD/"
            "RETURN_RECORD/PAYOR_BANK_ROUTING_NUMBER_CHECK_DIGIT"
        )
        return_bofd_field = (
            "/X937CHECK/FILE_HEADER_RECORD/CASH_LETTER_HEADER_RECORD/BUNDLE_HEADER_RECORD/"
            "RETURN_ADDENDUM_A_RECORD/BANK_OF_FIRST_DEPOSIT_ROUTING_NUMBER"
        )
        return_account_field = (
            "/X937CHECK/FILE_HEADER_RECORD/CASH_LETTER_HEADER_RECORD/BUNDLE_HEADER_RECORD/"
            "RETURN_ADDENDUM_A_RECORD/DEPOSIT_ACCOUNT_NUMBER_AT_BOFD"
        )
        return_reason_field = (
            "/X937CHECK/FILE_HEADER_RECORD/CASH_LETTER_HEADER_RECORD/BUNDLE_HEADER_RECORD/"
            "RETURN_RECORD/RETURN_REASON"
        )
        return_onus_field = (
            "/X937CHECK/FILE_HEADER_RECORD/CASH_LETTER_HEADER_RECORD/BUNDLE_HEADER_RECORD/"
            "RETURN_RECORD/ON_US_RETURN_RECORD"
        )

        required_fields = []
        if return_payor_field in df_return.columns and return_payor_check_digit_field in df_return.columns:
            df_return["RETURN_PAYOR_ROUTING"] = (
                df_return[return_payor_field].astype(str) + df_return[return_payor_check_digit_field].astype(str)
            )
            required_fields.append("RETURN_PAYOR_ROUTING")
        if return_bofd_field in df_return.columns:
            required_fields.append(return_bofd_field)
        if return_account_field in df_return.columns:
            required_fields.append(return_account_field)

        field_mapping = {
            "RETURN_PAYOR_ROUTING": "RETURN_PAYOR_ROUTING",
            return_bofd_field: "32_bofd_routing_number",
            return_account_field: "32_deposit_account_number_at_bofd",
        }

        if required_fields:
            na_counts = df_return[required_fields].isnull().sum()
            for field, count in na_counts.items():
                display_field = field_mapping.get(field, field)
                log_check(
                    f"Return Records Missing Value Check: {display_field}",
                    "FAIL" if count > 0 else "PASS",
                    f"{count:,} missing values in {display_field}",
                    "There should be no missing values. Investigate if count > 0.",
                )

            if return_onus_field in df_return.columns:
                onus_na_count = df_return[return_onus_field].isnull().sum()
                log_check(
                    "Return Records Missing Value Check: 31_on_us_return_record",
                    "FAIL" if onus_na_count > 0 else "PASS",
                    f"{onus_na_count:,} missing values in 31_on_us_return_record",
                    "There should be no missing values. Investigate if count > 0.",
                )

            for field in required_fields:
                display_field = field_mapping.get(field, field)
                top_vals = df_return[field].value_counts().head(5)
                if not top_vals.empty:
                    details_df = top_vals.reset_index()
                    details_df.columns = ["Value", "Count"]
                    log_check(
                        f"Return Records Top Values: {display_field}",
                        "INFO",
                        f"\n{details_df.to_string(index=False)}",
                        "Review if these values are expected.",
                    )

            if return_onus_field in df_return.columns:
                top_vals = df_return[return_onus_field].value_counts().head(5)
                if not top_vals.empty:
                    details_df = top_vals.reset_index()
                    details_df.columns = ["Value", "Count"]
                    log_check(
                        "Return Records Top Values: 31_on_us_return_record",
                        "INFO",
                        f"\n{details_df.to_string(index=False)}",
                        "Review if these values are expected.",
                    )

        if return_reason_field in df_return.columns:
            reason_counts = df_return[return_reason_field].value_counts().head(10)
            if not reason_counts.empty:
                reason_df = reason_counts.reset_index()
                reason_df.columns = ["Return_Reason", "Count"]
                log_check(
                    "Return Records Return Reason Distribution",
                    "INFO",
                    f"Top return reasons:\n{reason_df.to_string(index=False)}",
                    "Review if return reasons indicate systematic issues.",
                )

        log_check(
            "Return Records Endorsement Date Range",
            "INFO",
            "N/A (XML format does not have endorsement dates in this parser)",
            "This check applies to X937 format only.",
        )

    log_summary("Return Records Validation")

    df_legit.to_csv(f"forward_result_{current_time}.tsv", sep="\t", index=False)
    if len(df_return) > 0:
        df_return.to_csv(f"return_result_{current_time}.tsv", sep="\t", index=False)

    log_footer(check_results["FAIL"], check_results["WARN"])
    print("\nXML validation completed.")
