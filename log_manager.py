import logging
from datetime import datetime


check_results = {
    "PASS": 0,
    "WARN": 0,
    "INFO": 0,
    "FAIL": 0,
    "TOTAL": 0,
}


def setup_logging(log_filename: str):
    logging.basicConfig(
        filename=log_filename,
        filemode="w",
        format="%(message)s",
        level=logging.INFO,
    )


def log_header(dataset_name: str, file_count: int):
    logging.info("=" * 60)
    logging.info("DATA VALIDATION REPORT")
    logging.info("=" * 60)
    logging.info(f"Date: {datetime.now().strftime('%d-%b-%Y %H:%M')}")
    logging.info(f"Dataset: {dataset_name}")
    logging.info(f"Files processed: {file_count}\n")


def log_check(check_name: str, status: str, details: str, guideline: str):
    check_results["TOTAL"] += 1
    check_results[status] += 1

    status_symbol = {
        "PASS": "[PASS]",
        "WARN": "[WARN]",
        "FAIL": "[FAIL]",
        "INFO": "[INFO]",
    }.get(status, "[INFO]")

    logging.info(check_name)
    logging.info(f"Status: {status_symbol} {status}")
    logging.info(f"Details: {details}")
    logging.info(f"Guideline: {guideline}\n")


def log_summary(section_name: str):
    logging.info(f"\n========== {section_name} Summary ==========\n")
    logging.info(f"Total checks conducted: {check_results['TOTAL']}")
    logging.info(f"Passed: {check_results['PASS']}")
    logging.info(f"Warnings: {check_results['WARN']}")
    logging.info(f"Infos: {check_results['INFO']}")
    logging.info(f"Failed: {check_results['FAIL']}")
    logging.info("===========================================\n")


def log_footer(critical_issues: int, warnings: int):
    logging.info("=" * 60)
    logging.info("CLOSING NOTES")
    logging.info("=" * 60)

    if critical_issues:
        logging.info(f"Critical issues: {critical_issues}")

    if warnings:
        logging.info(f"Warnings: {warnings}")

    if not critical_issues and not warnings:
        logging.info("No issues detected. Data looks clean.")
