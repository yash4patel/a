import os
import logging
from datetime import datetime


class LogManager:
    """
    File-only log manager with helper methods.
    Use LogManager.setup(log_dir, logfile, loglevel) to create an instance.
    """

    def __init__(self, logger: logging.Logger, full_log_path: str, level: str = "INFO"):
        self.logger = logger
        self.logfile = full_log_path
        self.level = level.upper()
        # Tracking checks (for structured summaries)
        self.check_results = {"PASS": 0, "WARN": 0, "INFO": 0, "FAIL": 0, "TOTAL": 0}

    @staticmethod
    def setup(log_dir: str, logfile: str, loglevel: str = "INFO"):
        """
        Create file-only logger and return LogManager instance and full path.
        """
        os.makedirs(log_dir, exist_ok=True)
        full_log_path = os.path.join(log_dir, logfile)

        logger = logging.getLogger("ACH_Validator")
        # Remove any existing handlers to avoid duplicate logs
        if logger.handlers:
            for h in list(logger.handlers):
                logger.removeHandler(h)

        logger.setLevel(getattr(logging, loglevel.upper(), logging.INFO))
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

        file_handler = logging.FileHandler(full_log_path, mode="a")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # No console handlers (Option A)
        print(f"For more detail, please review the log file at: {full_log_path}")

        return LogManager(logger, full_log_path, loglevel), full_log_path

    # -------------------------
    # Helper methods for consistent structured logging
    # -------------------------
    def log_header(self, dataset_name: str, file_count: int):
        self.logger.info("=" * 60)
        self.logger.info(" DATA VALIDATION REPORT")
        self.logger.info("=" * 60)
        self.logger.info(f"Date: {datetime.now().strftime('%d-%b-%Y %H:%M')}")
        self.logger.info(f"Dataset: {dataset_name}")
        self.logger.info(f"Files processed: {file_count}\n")

    def log_check(self, check_name: str, status: str, details: str, guideline: str = ""):
        status = status.upper()
        if status not in self.check_results:
            status = "INFO"
        self.check_results["TOTAL"] += 1
        self.check_results[status] += 1

        symbol = {"PASS": "", "WARN": "", "FAIL": "", "INFO": ""}.get(status, "")
        self.logger.info(f"{check_name}")
        if status == "PASS":
            self.logger.info(f" Status : {symbol} {status}")
        elif status == "WARN":
            self.logger.warning(f" Status : {symbol} {status}")
        elif status in ("FAIL",):
            self.logger.error(f" Status : {symbol} {status}")
        else:
            self.logger.info(f" Status : {symbol} {status}")

        self.logger.info(f" Details : {details}")
        if guideline:
            self.logger.info(f" Guideline: {guideline}")
        self.logger.info("")

    def log_summary(self, section_name: str):
        self.logger.info(f"========== {section_name} Summary ==========")
        self.logger.info(f"Total checks conducted : {self.check_results['TOTAL']}")
        self.logger.info(f"Passed : {self.check_results['PASS']}")
        self.logger.info(f"Warnings : {self.check_results['WARN']}")
        self.logger.info(f"Infos : {self.check_results['INFO']}")
        self.logger.info(f"Failed : {self.check_results['FAIL']}")
        self.logger.info("===========================================\n")

    def log_footer(self, critical_issues: int = 0, warnings: int = 0):
        self.logger.info("=" * 60)
        self.logger.info("CLOSING NOTES")
        self.logger.info("=" * 60)
        if critical_issues:
            self.logger.error(f" Critical issues: {critical_issues}")
        if warnings:
            self.logger.warning(f"Warnings: {warnings}")
        if not critical_issues and not warnings:
            self.logger.info("No issues detected. Data looks clean.")
        self.logger.info("\n\n")
