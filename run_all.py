import os
import sys
from datetime import datetime
from time import perf_counter

from aba_entropy import ABAEntropyAnalyzer
from ach_mdv_validator import ACHMDVValidator
from batch_data_check import BatchDateCompletenessAnalyzer
from config import Config
from logger_utils import LogManager
import misc_functions
from ai_runner import run_ai_summary


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
    run_t0 = perf_counter()

    workflow_report = {
        "tenant_name": tenant_name,
        "sid": config.sid,
        "data_path": config.data_path,
        "log_file": full_log_path,
        "json_file": log_manager.jsonfile,
        "run_started_at": datetime.now().isoformat(timespec="seconds"),
        "config": {
            "extension": getattr(config, "extension", ""),
            "aba_number": getattr(config, "aba_number", ""),
            "aba_numbers": getattr(config, "aba_numbers", []),
            "max_error_percent": getattr(config, "max_error_percent", None),
        },
        "sections": {},
    }

    perf_enabled = bool(getattr(config, "perf_enabled", False))
    perf = {
        "enabled": bool(perf_enabled),
        "run": {},
        "sections": {},
        "dataset": {},
        "historical_estimate": {},
    }

    def _fmt_duration_s(s: float) -> str:
        try:
            s = float(s)
        except Exception:
            return "n/a"
        if s < 60:
            return f"{s:.1f}s"
        if s < 3600:
            return f"{s/60:.1f}m"
        return f"{s/3600:.2f}h"

    def _sec(name: str):
        t0 = perf_counter()

        class _Sec:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                dt = perf_counter() - t0
                perf["sections"].setdefault(name, {})
                perf["sections"][name]["duration_s"] = float(dt)
                return False

        return _Sec()

    if perf_enabled:
        # Dataset size stats for throughput & backfill estimate
        try:
            all_files = [
                f
                for f in os.listdir(config.data_path)
                if os.path.isfile(os.path.join(config.data_path, f))
            ]
            perf["dataset"]["files_total_in_path"] = int(len(all_files))
            # Prefer sampling only the configured extension if present (keeps stats focused on ACH).
            ext = str(getattr(config, "extension", "ACH") or "ACH").strip()
            if ext and not ext.startswith("."):
                ext = f".{ext}"
            if ext:
                all_files = [f for f in all_files if f.endswith(ext)]
            perf["dataset"]["files_total_matching_extension"] = int(len(all_files))
            max_n = int(getattr(config, "perf_max_files_for_size_stats", 2000) or 2000)
            sample = all_files[: max(0, min(len(all_files), max_n))]
            total_bytes = 0
            for fname in sample:
                try:
                    total_bytes += int(os.path.getsize(os.path.join(config.data_path, fname)))
                except Exception:
                    continue
            perf["dataset"]["size_sample_files"] = int(len(sample))
            perf["dataset"]["size_sample_bytes_total"] = int(total_bytes)
            perf["dataset"]["size_sample_avg_bytes_per_file"] = float(
                (total_bytes / len(sample)) if sample else 0.0
            )
        except Exception:
            pass

    logger.info("Validating file extensions...")
    with _sec("file_extension_validation"):
        is_valid, error_msg, invalid_files = validate_file_extensions(config.data_path, logger)
    workflow_report["sections"]["file_extension_validation"] = {
        "status": "PASSED" if is_valid else "FAILED",
        "invalid_files_count": int(len(invalid_files)),
        "invalid_files_sample": invalid_files[:20],
        "error": error_msg,
    }

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
        with _sec("ach_mdv_validator"):
            validator = ACHMDVValidator(config, log_manager)
            file_names = validator.validate_files()
            section1 = validator.summarize_results(len(file_names))
            workflow_report["sections"]["ach_mdv_validator"] = section1
            if perf_enabled:
                try:
                    dt = float(perf["sections"]["ach_mdv_validator"]["duration_s"])
                    total_records = int((section1.get("totals") or {}).get("records_total") or 0)
                    perf["sections"]["ach_mdv_validator"]["records_total"] = int(total_records)
                    if dt > 0:
                        perf["sections"]["ach_mdv_validator"]["records_per_s"] = float(
                            total_records / dt
                        )
                except Exception:
                    pass
    except Exception as e:
        logger.critical(f"ACH RDV Validator crashed: {e}")
        logger.debug(str(e))
        workflow_report["sections"]["ach_mdv_validator"] = {
            "section": "ACH RDV Validation",
            "status": "FAILED",
            "error": str(e),
        }

    try:
        with _sec("aba_entropy"):
            aba_analyzer = ABAEntropyAnalyzer(config, log_manager)
            ach_type, section2 = aba_analyzer.analyze()
            workflow_report["sections"]["aba_entropy"] = section2
            if not ach_type:
                ach_type = config.ach_type or "ODFI"
                logger.warning(
                    f"ABA analyzer returned no type; falling back to config value: {ach_type}"
                )
    except Exception as e:
        logger.critical(f"ABAEntropyAnalyzer crashed: {e}")
        logger.debug(str(e))
        ach_type = config.ach_type or "ODFI"
        workflow_report["sections"]["aba_entropy"] = {
            "section": "ABA Entropy",
            "status": "FAILED",
            "error": str(e),
        }

    try:
        with _sec("batch_data_check"):
            batch_date_analyzer = BatchDateCompletenessAnalyzer(config, log_manager)
            section3 = batch_date_analyzer.analyze(ach_type, config.extension)
            workflow_report["sections"]["batch_data_check"] = section3
    except Exception as e:
        logger.critical(f"BatchDateCompletenessAnalyzer crashed: {e}")
        logger.debug(str(e))
        workflow_report["sections"]["batch_data_check"] = {
            "section": "Batch Date Completeness",
            "status": "FAILED",
            "error": str(e),
        }

    run_dt = perf_counter() - run_t0
    perf["run"]["duration_s"] = float(run_dt)

    # Backfill / historical estimate (optional)
    if perf_enabled:
        try:
            workers = int(getattr(config, "perf_parallel_workers", 1) or 1)
            workers = max(1, workers)
        except Exception:
            workers = 1

        try:
            hist_bytes = int(getattr(config, "perf_historical_total_bytes", 0) or 0)
        except Exception:
            hist_bytes = 0
        try:
            hist_files = int(getattr(config, "perf_historical_total_files", 0) or 0)
        except Exception:
            hist_files = 0

        # Estimate throughput from observed size sample and *MDV section time* (dominant cost),
        # falling back to overall run time if missing.
        mdv_dt = float((perf.get("sections") or {}).get("ach_mdv_validator", {}).get("duration_s") or 0.0)
        denom_dt = mdv_dt if mdv_dt > 0 else run_dt
        sample_bytes = int((perf.get("dataset") or {}).get("size_sample_bytes_total") or 0)
        bytes_per_s = float(sample_bytes / denom_dt) if (denom_dt > 0 and sample_bytes > 0) else 0.0
        perf["run"]["throughput_bytes_per_s"] = float(bytes_per_s)
        perf["run"]["throughput_files_per_s"] = float(
            (int((perf.get("dataset") or {}).get("size_sample_files") or 0) / denom_dt)
            if denom_dt > 0
            else 0.0
        )

        # Derive historical bytes if only file count is supplied.
        if hist_bytes <= 0:
            # If user provided GB, prefer it.
            try:
                hist_gb = float(getattr(config, "perf_historical_total_gb", 0.0) or 0.0)
            except Exception:
                hist_gb = 0.0
            if hist_gb > 0:
                hist_bytes = int(hist_gb * 1024 * 1024 * 1024)

        if hist_bytes <= 0 and hist_files > 0:
            avg_bpf = float((perf.get("dataset") or {}).get("size_sample_avg_bytes_per_file") or 0.0)
            if avg_bpf > 0:
                hist_bytes = int(hist_files * avg_bpf)

        if hist_bytes > 0 and bytes_per_s > 0:
            est_s_single = hist_bytes / bytes_per_s
            est_s_parallel = est_s_single / workers
            perf["historical_estimate"] = {
                "basis": "bytes",
                "historical_total_bytes": int(hist_bytes),
                "observed_bytes_per_s": float(bytes_per_s),
                "parallel_workers": int(workers),
                "estimated_wall_time_s": float(est_s_parallel),
                "estimated_wall_time_human": _fmt_duration_s(est_s_parallel),
            }
            logger.info(
                "Historical backfill estimate (based on observed throughput): "
                f"{perf['historical_estimate']['estimated_wall_time_human']} "
                f"with {workers} worker(s)"
            )
        elif hist_files > 0 and perf["run"].get("throughput_files_per_s"):
            fps = float(perf["run"]["throughput_files_per_s"] or 0.0)
            if fps > 0:
                est_s_single = hist_files / fps
                est_s_parallel = est_s_single / workers
                perf["historical_estimate"] = {
                    "basis": "files",
                    "historical_total_files": int(hist_files),
                    "observed_files_per_s": float(fps),
                    "parallel_workers": int(workers),
                    "estimated_wall_time_s": float(est_s_parallel),
                    "estimated_wall_time_human": _fmt_duration_s(est_s_parallel),
                }
                logger.info(
                    "Historical backfill estimate (based on observed throughput): "
                    f"{perf['historical_estimate']['estimated_wall_time_human']} "
                    f"with {workers} worker(s)"
                )
        else:
            perf["historical_estimate"] = {
                "basis": None,
                "note": "Provide perf_historical_total_bytes or perf_historical_total_files to compute an estimate.",
            }

    workflow_report["performance"] = perf

    logger.info("=== WORKFLOW COMPLETED ===")
    workflow_report["run_finished_at"] = datetime.now().isoformat(timespec="seconds")
    try:
        log_manager.write_json_report(workflow_report)
    except Exception:
        pass

    # Optional: Generate AI / agent-based detailed summary from the combined JSON.
    try:
        if getattr(config, "ai_summary_enabled", False):
            run_ai_summary(
                report_json_path=log_manager.jsonfile,
                base_url=getattr(config, "ollama_base_url", None),
                model=getattr(config, "ollama_model", None),
                dry_run=bool(getattr(config, "ai_summary_dry_run", True)),
                allow_sensitive_evidence=bool(getattr(config, "ai_allow_sensitive_evidence", False)),
                include_sanitized_samples=bool(getattr(config, "ai_include_sanitized_samples", False)),
                max_samples=int(getattr(config, "ai_max_samples", 20)),
                timeout_s=int(getattr(config, "ai_timeout_s", 180)),
            )
    except Exception as e:
        logger.warning(f"AI summary generation skipped/failed: {e}")

    print(f"\nDetails and logs have been saved to: {full_log_path}")
    print(f"JSON summary saved to: {log_manager.jsonfile}")


if __name__ == "__main__":
    main()

