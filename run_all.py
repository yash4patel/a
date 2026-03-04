import os
import sys
from datetime import datetime

from aba_entropy import ABAEntropyAnalyzer
from ach_mdv_validator import ACHMDVValidator
from batch_data_check import BatchDateCompletenessAnalyzer
from config import Config
from logger_utils import LogManager
import misc_functions


def validate_file_extensions(data_path, logger=None):
    """
    Validate that all files in the data path have .ACH extension (case sensitive).
    Returns (is_valid, error_message, invalid_files_list)
    """
    try:
        all_files = [
            f
            for f in os.listdir(data_path)
            if os.path.isfile(os.path.join(data_path, f))
        ]

        if not all_files:
            return True, None, []

        invalid_files = []
        for filename in all_files:
            if not filename.endswith(".ACH"):
                invalid_files.append(filename)

        if invalid_files:
            error_msg = (
                "Please ensure the extension is correct, only .ACH is acceptable. "
                "It is case sensitive."
            )
            return False, error_msg, invalid_files

        return True, None, []

    except Exception as e:
        error_msg = f"Error checking file extensions: {e}"
        if logger:
            logger.error(error_msg)
        return False, error_msg, []


def main():
    if misc_functions.is_interactive():
        print("Interactive mode detected. Please run from command line.")
        return

    if len(sys.argv) != 2:
        print("Usage: python run_all.py <config_file.ini>")
        sys.exit(1)

    config_file = sys.argv[1]
    if not os.path.isfile(config_file):
        print(f"Config file not found: {config_file}")
        sys.exit(1)

    try:
        config = Config(config_file)
    except Exception as e:
        print(f"Failed to load config: {e}")
        sys.exit(1)

    if not os.path.isdir(config.data_path):
        print(f"Data path does not exist: {config.data_path}")
        sys.exit(1)

    if not config.is_folded:
        print("Please Provide Folded Data!")
        sys.exit(1)

    if not os.path.isdir(config.log_path):
        try:
            os.makedirs(config.log_path)
        except Exception as e:
            print(f"Could not create log directory {config.log_path}: {e}")
            sys.exit(1)

    tenant_name = config.tenant_name.strip()
    if not tenant_name:
        print("Tenant name is blank")
        sys.exit(1)

    logfile = (
        f"{tenant_name}_{config.sid}_{datetime.now().strftime('%Y%m%d_%H%M')}.ACH.log"
    )

    log_manager, full_log_path = LogManager.setup(
        config.log_path, logfile, config.log_level
    )
    logger = log_manager.logger

    logger.info("=== STARTING ACH VALIDATION WORKFLOW ===")

    logger.info("Validating file extensions...")
    is_valid, error_msg, invalid_files = validate_file_extensions(config.data_path, logger)

    if not is_valid:
        logger.error("=" * 40)
        logger.error("*** FILE EXTENSION VALIDATION FAILED ***")
        logger.error("=" * 40)
        logger.error(error_msg)
        logger.error("")
        logger.error(f"Found {len(invalid_files)} file(s) with incorrect extension:")
        for idx, filename in enumerate(invalid_files[:20], 1):
            logger.error(f"  {idx}. {filename}")
        if len(invalid_files) > 20:
            logger.error(f"  ... and {len(invalid_files) - 20} more files")
        logger.error("")
        logger.error("=" * 40)

        print("=" * 40)
        print("*** FILE EXTENSION VALIDATION FAILED ***")
        print("=" * 40)
        print(error_msg)
        print(f"\nFound {len(invalid_files)} file(s) with incorrect extension.")
        print("Please check the log file for details:")
        print(f"  {full_log_path}")
        print("=" * 40)
    else:
        logger.info("File extension validation: PASSED (all files have .ACH extension)")

    try:
        validator = ACHMDVValidator(config, log_manager)
        file_names = validator.validate_files()
        validator.summarize_results(len(file_names))
    except Exception as e:
        logger.critical(f"ACH RDV Validator crashed: {e}")
        logger.debug(str(e))

    try:
        aba_analyzer = ABAEntropyAnalyzer(config, log_manager)
        ach_type = aba_analyzer.analyze()
        if not ach_type:
            ach_type = config.ach_type or "ODFI"
            logger.warning(
                f"ABA analyzer returned no type; falling back to config value: {ach_type}"
            )
    except Exception as e:
        logger.critical(f"ABAEntropyAnalyzer crashed: {e}")
        logger.debug(str(e))
        ach_type = config.ach_type or "ODFI"

    try:
        batch_date_analyzer = BatchDateCompletenessAnalyzer(config, log_manager)
        batch_date_analyzer.analyze(ach_type, config.extension)
    except Exception as e:
        logger.critical(f"BatchDateCompletenessAnalyzer crashed: {e}")
        logger.debug(str(e))

    logger.info("=== WORKFLOW COMPLETED ===")
    print(f"\nDetails and logs have been saved to: {full_log_path}")


if __name__ == "__main__":
    main()

