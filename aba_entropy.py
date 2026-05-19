import json
import math
import os
import traceback
from copy import deepcopy
from typing import Any, Dict, Optional, Tuple

import folder_tools


class ABAEntropyAnalyzer:
    """
    ABA-based entropy analyzer to suggest ODFI vs RDFI.

    Metadata-driven contract:
    - line decoding
    - metric extraction (record key + field slice)
    - normalization
    - entropy scoring
    - decision logic
    """

    def __init__(self, config, log_manager):
        self.config = config
        self.log = log_manager
        self.logger = log_manager.logger

        self.metadata = self._load_metadata()
        self.metric_counts: Dict[str, Dict[str, int]] = {}
        for metric in self.metadata.get("metrics", []):
            metric_id = str(metric.get("id") or "").strip()
            if metric_id:
                self.metric_counts[metric_id] = {}

        # Backward-compatibility aliases used elsewhere in the workflow/reporting.
        self.aba_5_counts = self.metric_counts.get("type5_odfi", {})
        self.aba_6_counts = self.metric_counts.get("type6_rdfi", {})
        self.last_report = None

    def _build_default_metadata(self) -> Dict[str, Any]:
        return {
            "section_name": "ABA Entropy",
            "file_selection": {
                "extension": None,
                # Optional regex filters on filename (post extension filtering)
                "include_filenames_regex": None,
                "exclude_filenames_regex": None,
            },
            "progress": {
                "enabled": True,
                "update_delta_percent": None,
            },
            "line_processing": {
                "encoding": "ascii",
                "decode_errors": "replace",
                "record_type_position_0_based": 0,
                # How to handle lines shorter than the largest end-slice:
                # - "skip": skip this line
                # - "pad": right-pad spaces to required length
                "short_line_policy": "skip",
            },
            "metrics": [
                {
                    "id": "type5_odfi",
                    "label": "ODFI (Type-5)",
                    "record_key": 5,
                    "field_slice_0_based": [81, 87],
                    "normalize": {
                        "strip": True,
                        "digits_only": True,
                        "skip_if_empty": True,
                        # Optional length guards after normalization
                        "min_len": None,
                        "max_len": None,
                    },
                    # How to handle missing field values after slicing:
                    # - "skip": skip value
                    # - "keep": keep empty string (subject to skip_if_empty)
                    "missing_field_policy": "skip",
                },
                {
                    "id": "type6_rdfi",
                    "label": "RDFI (Type-6)",
                    "record_key": 6,
                    "field_slice_0_based": [5, 12],
                    "normalize": {
                        "strip": True,
                        "digits_only": True,
                        "skip_if_empty": True,
                        "min_len": None,
                        "max_len": None,
                    },
                    "missing_field_policy": "skip",
                },
            ],
            "scoring": {
                "method": "entropy",
                # Preserve existing behavior: signed entropy (negative), not -entropy
                "entropy_signed": True,
                # Treat metrics with totals < this value as "missing" for decision.
                "minimum_total_per_metric": 1,
            },
            "decision": {
                "left_metric": "type5_odfi",
                "operator": ">",
                "right_metric": "type6_rdfi",
                # Policy branches when comparison is not straightforward
                # Values: "if_true" | "if_false"
                "on_equal": "if_false",
                "on_missing_metric": "if_false",
                "on_invalid_operator": "if_true",
                "if_true": {"ach_type": "ODFI", "message": "This appears to be ODFI data."},
                "if_false": {"ach_type": "RDFI", "message": "This appears to be RDFI data."},
            },
            "reporting": {
                "top_n_values_per_metric": 10,
                "include_value_samples": False,
            },
        }

    def _deep_merge_dicts(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        out = deepcopy(base)
        for key, value in (override or {}).items():
            if isinstance(value, dict) and isinstance(out.get(key), dict):
                out[key] = self._deep_merge_dicts(out[key], value)
            else:
                out[key] = value
        return out

    def _load_metadata(self) -> Dict[str, Any]:
        md = self._build_default_metadata()
        override = getattr(self.config, "aba_entropy_metadata", None)
        if isinstance(override, dict) and override:
            md = self._deep_merge_dicts(md, override)
        return md

    def _extract_record_key(self, line: str) -> Optional[int]:
        try:
            pos = int(self.metadata.get("line_processing", {}).get("record_type_position_0_based", 0))
            if pos < 0 or pos >= len(line):
                return None
            return int(line[pos])
        except Exception:
            return None

    def _normalize_value(self, raw_value: str, normalize_cfg: Dict[str, Any]) -> str:
        value = raw_value
        if normalize_cfg.get("strip", True):
            value = value.strip()
        if normalize_cfg.get("digits_only", False):
            value = "".join(ch for ch in value if ch.isdigit())
        if normalize_cfg.get("upper", False):
            value = value.upper()
        # Optional length policy after normalization
        try:
            min_len = normalize_cfg.get("min_len", None)
            max_len = normalize_cfg.get("max_len", None)
            if min_len is not None and len(value) < int(min_len):
                return ""
            if max_len is not None and len(value) > int(max_len):
                return ""
        except Exception:
            pass
        return value

    def _entropy(self, counts) -> float:
        total = sum(counts)
        if total <= 0:
            return 0.0
        signed = bool(self.metadata.get("scoring", {}).get("entropy_signed", True))
        score = sum((i / total) * math.log2(i / total) for i in counts if i > 0)
        return float(score if signed else (-score))

    def analyze(self) -> Tuple[str, Dict[str, Any]]:
        try:
            self.logger.info("")
            self.logger.info("=" * 70)
            self.logger.info("=== STARTING SECTION 2 ODFI/RDFI DETECTION ===")
            self.logger.info("=" * 70)

            file_sel = self.metadata.get("file_selection", {}) if isinstance(self.metadata.get("file_selection"), dict) else {}
            extension = file_sel.get("extension")
            fileNames = folder_tools.get_filenames(self.config.data_path, extension=extension)
            # Support common alias keys
            include_re = file_sel.get("include_filenames_regex", None)
            if include_re is None:
                include_re = file_sel.get("include_files_regex", None)
            exclude_re = file_sel.get("exclude_filenames_regex", None)
            if exclude_re is None:
                exclude_re = file_sel.get("exclude_files_regex", None)
            if include_re:
                try:
                    import re
                    rx = re.compile(str(include_re))
                    fileNames = [n for n in fileNames if rx.search(n)]
                except Exception:
                    pass
            if exclude_re:
                try:
                    import re
                    rx = re.compile(str(exclude_re))
                    fileNames = [n for n in fileNames if not rx.search(n)]
                except Exception:
                    pass
            total_files = len(fileNames)
            self.logger.info(f"Starting ABA entropy analysis on {total_files} files.")
            progress = self.metadata.get("progress", {}) if isinstance(self.metadata.get("progress"), dict) else {}
            progress_enabled = bool(progress.get("enabled", True))
            update_delta = progress.get("update_delta_percent")
            if update_delta is None:
                update_delta = progress.get("percent_step")
            try:
                update_delta = int(update_delta) if update_delta is not None else int(getattr(self.config, "update_delta", 5))
            except Exception:
                update_delta = int(getattr(self.config, "update_delta", 5))
            next_update = update_delta
            file_counter = 0

            decode_encoding = self.metadata.get("line_processing", {}).get("encoding", "ascii")
            decode_errors = self.metadata.get("line_processing", {}).get("decode_errors", "replace")

            metrics = self.metadata.get("metrics", [])
            metrics_by_key: Dict[int, list] = {}
            for metric in metrics:
                try:
                    metric_key = int(metric.get("record_key"))
                except Exception:
                    continue
                metrics_by_key.setdefault(metric_key, []).append(metric)

            for fname in fileNames:
                file_counter += 1
                if progress_enabled and round(100 * file_counter / max(1, total_files)) >= next_update:
                    self.logger.info(f"ABA Analysis Progress: {next_update}% done")
                    next_update += update_delta

                filepath = os.path.join(self.config.data_path, fname)
                try:
                    with open(filepath, "rb") as f:
                        for line_bytes in f:
                            try:
                                line = line_bytes.decode(decode_encoding, decode_errors)
                                key = self._extract_record_key(line)
                            except Exception:
                                continue

                            if key is None or key not in metrics_by_key:
                                continue

                            for metric in metrics_by_key.get(key, []):
                                metric_id = str(metric.get("id") or "").strip()
                                if not metric_id:
                                    continue

                                field_slice = metric.get("field_slice_0_based") or []
                                if not isinstance(field_slice, list) or len(field_slice) != 2:
                                    continue
                                try:
                                    start = int(field_slice[0])
                                    end = int(field_slice[1])
                                except Exception:
                                    continue
                                if start < 0 or end <= start:
                                    continue

                                short_policy = str(self.metadata.get("line_processing", {}).get("short_line_policy", "skip")).strip().lower()
                                # Support alias values
                                if short_policy in ("skip_line", "skipfile", "skip"):
                                    short_policy = "skip"
                                if short_policy in ("pad_line", "pad"):
                                    short_policy = "pad"
                                if end > len(line):
                                    if short_policy == "pad":
                                        line_eff = line + (" " * (end - len(line)))
                                    else:
                                        continue
                                else:
                                    line_eff = line

                                raw_value = line_eff[start:end]
                                normalize_cfg = metric.get("normalize") or {}
                                if not isinstance(normalize_cfg, dict):
                                    normalize_cfg = {}
                                value = self._normalize_value(raw_value, normalize_cfg)
                                if not value:
                                    missing_policy = str(metric.get("missing_field_policy", "skip")).strip().lower()
                                    if missing_policy == "keep":
                                        value = ""
                                if not value and normalize_cfg.get("skip_if_empty", True):
                                    continue

                                counts = self.metric_counts.setdefault(metric_id, {})
                                counts[value] = counts.get(value, 0) + 1
                except Exception as e:
                    self.logger.error(f"Failed reading file {fname} for ABA analysis: {e}")
                    self.logger.debug(traceback.format_exc())
                    continue

            ach_type, report = self._report_results()
            self.last_report = report

            self.logger.info("")
            self.logger.info("=" * 70)
            self.logger.info("=== FINISHED SECTION 2 ABA ENTROPY ANALYSIS ===")
            self.logger.info("=" * 70)
            self.logger.info("")

            return ach_type, report
        except Exception as e:
            self.logger.critical(f"ABAEntropyAnalyzer failed: {e}")
            self.logger.debug(traceback.format_exc())
            self.logger.info("")
            self.logger.info("=" * 70)
            self.logger.info("=== FINISHED ABA ENTROPY ANALYSIS ===")
            self.logger.info("=" * 70)
            self.logger.info("")
            report = {"section": "ABA Entropy", "status": "FAILED", "error": str(e)}
            self.last_report = report
            return "", report

    def _report_results(self) -> Tuple[str, Dict[str, Any]]:
        try:
            metric_scores: Dict[str, float] = {}
            metric_totals: Dict[str, int] = {}
            metric_distinct: Dict[str, int] = {}
            metric_top_values: Dict[str, Any] = {}
            reporting = self.metadata.get("reporting", {}) if isinstance(self.metadata.get("reporting"), dict) else {}
            try:
                top_n = int(reporting.get("top_n_values_per_metric", reporting.get("top_values_per_metric", 10)) or 10)
            except Exception:
                top_n = 10
            include_samples = bool(reporting.get("include_value_samples", False))
            for metric in self.metadata.get("metrics", []):
                metric_id = str(metric.get("id") or "").strip()
                if not metric_id:
                    continue
                counts = self.metric_counts.get(metric_id, {})
                values = list(counts.values())
                metric_scores[metric_id] = self._entropy(values)
                metric_totals[metric_id] = int(sum(values))
                metric_distinct[metric_id] = int(len(counts))
                if include_samples and isinstance(counts, dict):
                    metric_top_values[metric_id] = [
                        {"value": v, "count": int(c)}
                        for v, c in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[: max(0, top_n)]
                    ]

            decision = self.metadata.get("decision", {}) if isinstance(self.metadata.get("decision"), dict) else {}
            left_metric = str(decision.get("left_metric") or "").strip()
            right_metric = str(decision.get("right_metric") or "").strip()
            op = str(decision.get("operator") or ">").strip()

            scoring = self.metadata.get("scoring", {}) if isinstance(self.metadata.get("scoring"), dict) else {}
            try:
                min_total = int(scoring.get("minimum_total_per_metric", 1) or 1)
            except Exception:
                min_total = 1

            def _metric_available(mid: str) -> bool:
                if not mid:
                    return False
                return int(metric_totals.get(mid, 0)) >= int(min_total)

            left_available = _metric_available(left_metric)
            right_available = _metric_available(right_metric)

            left_score = float(metric_scores.get(left_metric, 0.0))
            right_score = float(metric_scores.get(right_metric, 0.0))

            missing_policy = str(decision.get("missing_metric_policy", decision.get("on_missing_metric", "if_false"))).strip()
            if missing_policy == "use_zero":
                # If insufficient data, use 0.0 as the score for that side.
                if not left_available:
                    left_score = 0.0
                if not right_available:
                    right_score = 0.0
            else:
                # If either side missing, follow on_missing_metric.
                if not left_available or not right_available:
                    on_missing = str(decision.get("on_missing_metric", "if_false")).strip()
                    pick = on_missing if on_missing in ("if_true", "if_false") else "if_false"
                    selected = decision.get(pick, {}) if isinstance(decision.get(pick), dict) else {}
                    ach_type = str(selected.get("ach_type") or "").strip()
                    msg = str(selected.get("message") or "Could not classify ACH type from ABA entropy.")
                    report = {
                        "section": "ABA Entropy",
                        "status": "OK",
                        "detected_ach_type": ach_type,
                        "entropy": {
                            "type5_odfi": float(metric_scores.get("type5_odfi", 0.0)),
                            "type6_rdfi": float(metric_scores.get("type6_rdfi", 0.0)),
                        },
                        "counts": {
                            "type5_distinct": int(metric_distinct.get("type5_odfi", 0)),
                            "type5_total": int(metric_totals.get("type5_odfi", 0)),
                            "type6_distinct": int(metric_distinct.get("type6_rdfi", 0)),
                            "type6_total": int(metric_totals.get("type6_rdfi", 0)),
                        },
                        "metadata": {
                            "decision": {
                                "left_metric": left_metric,
                                "operator": op,
                                "right_metric": right_metric,
                                "left_score": float(left_score),
                                "right_score": float(right_score),
                                "reason": "missing_metric",
                            },
                            "metrics": {
                                mid: {
                                    "entropy": float(metric_scores.get(mid, 0.0)),
                                    "distinct": int(metric_distinct.get(mid, 0)),
                                    "total": int(metric_totals.get(mid, 0)),
                                    **({"top_values": metric_top_values.get(mid, [])} if include_samples else {}),
                                }
                                for mid in metric_scores.keys()
                            },
                        },
                    }
                    self.logger.info("")
                    self.logger.info("ABA Entropy Analysis Results:")
                    self.logger.info("-" * 70)
                    self.logger.info(f"Entropy ODFI (Type-5): {float(metric_scores.get('type5_odfi', 0.0)):.4f}")
                    self.logger.info(f"Entropy RDFI (Type-6): {float(metric_scores.get('type6_rdfi', 0.0)):.4f}")
                    self.logger.info("")
                    self.logger.info(f"*** DETECTED: {msg} ***")
                    return ach_type, report

            if op == ">":
                decision_result = left_score > right_score
            elif op == ">=":
                decision_result = left_score >= right_score
            elif op == "<":
                decision_result = left_score < right_score
            elif op == "<=":
                decision_result = left_score <= right_score
            elif op == "==":
                decision_result = left_score == right_score
            else:
                on_invalid = str(decision.get("on_invalid_operator", "if_true")).strip()
                decision_result = True if on_invalid == "if_true" else False

            if left_score == right_score and op in (">", ">=", "<", "<="):
                on_equal = str(decision.get("on_equal", "if_false")).strip()
                decision_result = True if on_equal == "if_true" else False

            selected = decision.get("if_true", {}) if decision_result else decision.get("if_false", {})
            if not isinstance(selected, dict):
                selected = {}
            ach_type = str(selected.get("ach_type") or "").strip()
            msg = str(selected.get("message") or "Could not classify ACH type from ABA entropy.")

            ent_aba_5 = float(metric_scores.get("type5_odfi", 0.0))
            ent_aba_6 = float(metric_scores.get("type6_rdfi", 0.0))
            aba_5_sum = int(metric_totals.get("type5_odfi", 0))
            aba_6_sum = int(metric_totals.get("type6_rdfi", 0))

            report = {
                "section": "ABA Entropy",
                "status": "OK",
                "detected_ach_type": ach_type,
                "entropy": {"type5_odfi": ent_aba_5, "type6_rdfi": ent_aba_6},
                "counts": {
                    "type5_distinct": int(metric_distinct.get("type5_odfi", 0)),
                    "type5_total": aba_5_sum,
                    "type6_distinct": int(metric_distinct.get("type6_rdfi", 0)),
                    "type6_total": aba_6_sum,
                },
                "metadata": {
                    "decision": {
                        "left_metric": left_metric,
                        "operator": op,
                        "right_metric": right_metric,
                        "left_score": float(left_score),
                        "right_score": float(right_score),
                        "reason": "compare",
                    },
                    "metrics": {
                        mid: {
                            "entropy": float(metric_scores.get(mid, 0.0)),
                            "distinct": int(metric_distinct.get(mid, 0)),
                            "total": int(metric_totals.get(mid, 0)),
                            **({"top_values": metric_top_values.get(mid, [])} if include_samples else {}),
                        }
                        for mid in metric_scores.keys()
                    },
                },
            }

            self.logger.info("")
            self.logger.info("ABA Entropy Analysis Results:")
            self.logger.info("-" * 70)
            self.logger.info(f"Entropy ODFI (Type-5): {ent_aba_5:.4f}")
            self.logger.info(f"Entropy RDFI (Type-6): {ent_aba_6:.4f}")
            self.logger.info(
                f"ABA counts (Type-5): {len(self.aba_5_counts)} distinct, total {aba_5_sum}"
            )
            self.logger.info(
                f"ABA counts (Type-6): {len(self.aba_6_counts)} distinct, total {aba_6_sum}"
            )
            self.logger.info("")
            self.logger.info(f"*** DETECTED: {msg} ***")

            return ach_type, report
        except Exception as e:
            self.logger.error(f"Error reporting ABA entropy results: {e}")
            self.logger.debug(traceback.format_exc())
            return "", {"section": "ABA Entropy", "status": "FAILED", "error": str(e)}

