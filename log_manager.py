import logging
import os
from datetime import datetime


check_results = {
    "PASS": 0,
    "WARN": 0,
    "INFO": 0,
    "FAIL": 0,
    "TOTAL": 0,
}
check_history = []
_summary_cursor = 0
_LOGGER_NAME = "X937_XML_Validator"


def setup_logging(log_filename: str):
    """Configure file logging with ACH-like format and reset counters."""
    global check_history, _summary_cursor
    for key in check_results:
        check_results[key] = 0
    check_history = []
    _summary_cursor = 0

    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
    logger.setLevel(logging.INFO)

    file_handler = logging.FileHandler(log_filename, mode="w")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)
    logger.propagate = False

    print(f"For more detail, please review the log file at: {os.path.abspath(log_filename)}")


def _logger():
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        # Fallback to root logger if setup_logging wasn't called for some reason.
        return logging.getLogger()
    return logger


def log_section_start(title: str):
    logger = _logger()
    logger.info("")
    logger.info("=" * 70)
    logger.info(f"=== STARTING {title} ===")
    logger.info("=" * 70)


def log_section_end(title: str):
    logger = _logger()
    logger.info("")
    logger.info("=" * 70)
    logger.info(f"=== FINISHED {title} ===")
    logger.info("=" * 70)
    logger.info("")


def log_header(dataset_name: str, file_count: int):
    logger = _logger()
    logger.info("=" * 60)
    logger.info(" DATA VALIDATION REPORT")
    logger.info("=" * 60)
    logger.info(f"Date: {datetime.now().strftime('%d-%b-%Y %H:%M')}")
    logger.info(f"Dataset: {dataset_name}")
    logger.info(f"Files processed: {file_count}")
    logger.info("")


def log_check(check_name: str, status: str, details: str, guideline: str):
    logger = _logger()
    normalized = status.upper()
    if normalized not in check_results:
        normalized = "INFO"

    check_results["TOTAL"] += 1
    check_results[normalized] += 1
    check_history.append({"name": check_name, "status": normalized})

    logger.info(check_name)
    if normalized == "PASS":
        logger.info(f" Status : {normalized}")
    elif normalized == "WARN":
        logger.warning(f" Status : {normalized}")
    elif normalized == "FAIL":
        logger.error(f" Status : {normalized}")
    else:
        logger.info(f" Status : {normalized}")
    logger.info(f" Details : {details}")
    if guideline:
        logger.info(f" Guideline: {guideline}")
    logger.info("")


def log_summary(section_name: str):
    global _summary_cursor
    logger = _logger()
    section_history = check_history[_summary_cursor:]
    _summary_cursor = len(check_history)

    section_counts = {"PASS": 0, "WARN": 0, "INFO": 0, "FAIL": 0}
    section_names = {"PASS": [], "WARN": [], "INFO": [], "FAIL": []}
    for entry in section_history:
        status = entry["status"]
        if status not in section_counts:
            continue
        section_counts[status] += 1
        section_names[status].append(entry["name"])

    def _render_checks(status: str, max_items: int = 6) -> str:
        names = section_names[status]
        if not names:
            return "None"
        if len(names) <= max_items:
            return "; ".join(names)
        remaining = len(names) - max_items
        return f"{'; '.join(names[:max_items])}; ... (+{remaining} more)"

    def _render_one_line(status: str, label: str, max_items: int = 3) -> str:
        names = section_names[status]
        if not names:
            return f"{label}: none."
        if len(names) <= max_items:
            return f"{label}: " + "; ".join(names) + "."
        remaining = len(names) - max_items
        return f"{label}: {'; '.join(names[:max_items])}; ... (+{remaining} more)."

    logger.info(f"========== {section_name} Summary ==========")
    logger.info(f"Total checks conducted : {len(section_history)}")
    logger.info(f"Passed : {section_counts['PASS']}")
    logger.info(f"  - PASS checks: {_render_checks('PASS')}")
    logger.info(f"Warnings : {section_counts['WARN']}")
    logger.info(f"  - WARN checks: {_render_checks('WARN')}")
    logger.info(f"Infos : {section_counts['INFO']}")
    logger.info(f"  - INFO checks: {_render_checks('INFO')}")
    logger.info(f"Failed : {section_counts['FAIL']}")
    logger.info(f"  - FAIL checks: {_render_checks('FAIL')}")
    logger.info(f"One-line failed summary: {_render_one_line('FAIL', 'Failed checks')}")
    logger.info(f"One-line passed summary: {_render_one_line('PASS', 'Worked/passed checks')}")
    logger.info("===========================================")
    logger.info("")


def log_individual_check_results():
    """ACH-like compact list of individual check statuses."""
    logger = _logger()
    logger.info("Individual Check Results:")
    logger.info("-" * 40)
    if not check_history:
        logger.info("No checks recorded.")
        logger.info("")
        return
    for entry in check_history:
        logger.info(f"{entry['name']:.<50} {entry['status']}")
    logger.info("")


def log_footer(critical_issues: int, warnings: int):
    logger = _logger()
    logger.info("=" * 60)
    logger.info("CLOSING NOTES")
    logger.info("=" * 60)

    if critical_issues:
        logger.error(f" Critical issues: {critical_issues}")

    if warnings:
        logger.warning(f"Warnings: {warnings}")

    if not critical_issues and not warnings:
        logger.info("No issues detected. Data looks clean.")
    logger.info("")
