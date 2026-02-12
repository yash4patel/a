import configparser
import os
import sys
import traceback
from datetime import datetime

from log_manager import setup_logging


def main():
    """Main entry point for data validation."""
    if len(sys.argv) != 2:
        print("Usage: python main.py <path_to_config.ini>")
        sys.exit(1)

    config_file = sys.argv[1]
    if not os.path.isfile(config_file):
        print(f"Config file not found: {config_file}")
        sys.exit(1)

    config = configparser.ConfigParser()
    try:
        config.read(config_file)
    except Exception as e:
        print(f"Error reading config file: {e}")
        sys.exit(1)

    try:
        validation_type = config.get("GENERAL", "validation_type").lower().strip()
        verbose = config.getboolean("GENERAL", "verbose_output")
        input_path = config.get("DATA", "input_path")
        sample_days = config.getint("DATA", "sample_days")
        tenant_name = config.get("DATA", "tenant_name")
    except configparser.NoSectionError as e:
        print(f"ERROR: Missing section in config.ini: {e}")
        sys.exit(1)
    except configparser.NoOptionError as e:
        print(f"ERROR: Missing option in config.ini: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR parsing config.ini: {e}")
        sys.exit(1)

    if validation_type not in ["x937", "xml"]:
        print("ERROR: validation_type must be 'x937' or 'xml'")
        print(f"Current value: '{validation_type}'")
        print("\nUpdate config.ini:")
        print("  [GENERAL]")
        print("  validation_type = xml     # or x937")
        sys.exit(1)

    if not os.path.exists(input_path):
        print(f"ERROR: Input path does not exist: {input_path}")
        print("\nPlease update config.ini with a valid path:")
        print("  [DATA]")
        print(f"  input_path = {input_path}")
        sys.exit(1)

    if not os.path.isdir(input_path):
        print(f"ERROR: Input path is not a directory: {input_path}")
        sys.exit(1)

    suffix = "XML" if validation_type == "xml" else "X937"
    log_filename = f"{tenant_name}_{datetime.now().strftime('%Y%m%d_%H%M')}.{suffix}.log"

    try:
        setup_logging(log_filename)
    except Exception as e:
        print(f"ERROR setting up logging: {e}")
        sys.exit(1)

    if verbose:
        print("\n" + "=" * 70)
        print("  DATA VALIDATION SYSTEM")
        print("=" * 70)
        print(f"\n  Validation Type : {validation_type.upper()}")
        print(f"  Input Path      : {input_path}")
        print(f"  Sample Days     : {sample_days}")
        print(f"  Log File        : {log_filename}")
        print(f"  Started         : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("\n" + "=" * 70 + "\n")

    try:
        if validation_type == "x937":
            if verbose:
                print("Launching X937 validation...\n")

            from x9_check_validation import process_x9_files

            try:
                our_aba = config.get("X937", "our_aba").strip()
            except (configparser.NoSectionError, configparser.NoOptionError):
                print("ERROR: Missing [X937] section or 'our_aba' option in config.ini")
                sys.exit(1)

            process_x9_files(input_path, sample_days, our_aba, config)
        else:
            if verbose:
                print("Launching XML validation...\n")
            import xml_validation

            xml_validation.run_xml_validation(config)

        if verbose:
            print("\n" + "=" * 70)
            print(" VALIDATION COMPLETED SUCCESSFULLY")
            print("=" * 70)
            print(f"\n  Log file :  {log_filename}")
            print(f"  Completed:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            print("=" * 70 + "\n")

    except ModuleNotFoundError as e:
        print(f"ERROR: Required module not found: {e}")
        print("\nMake sure all required modules are installed:")
        print("  - xml_validation.py (for XML)")
        print("  - x9_check_validation.py (for X937)")
        print("  - log_manager.py")
        traceback.print_exc()
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"ERROR: File not found: {e}")
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"ERROR during validation: {e}")
        print("\nFull traceback:")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
