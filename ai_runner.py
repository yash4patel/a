import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class OllamaConfig:
    base_url: str
    model: str


def _read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=False, default=str, ensure_ascii=False)


def _redact_path(p: Optional[str]) -> Optional[str]:
    if not p:
        return p
    p = str(p)
    # Preserve only the basename to reduce leakage of internal mount points / customer paths.
    base = os.path.basename(p.rstrip("/"))
    return base or "<redacted>"


def _scrub_encoding_integrity_for_llm(enc: Any, *, allow_sensitive_evidence: bool) -> Any:
    """
    The validator's encoding integrity samples may include raw line previews.
    For LLM safety, we never forward raw previews and, by default, we also redact filenames/line numbers.
    """
    if not isinstance(enc, dict):
        return enc

    out: Dict[str, Any] = {}
    for k, v in enc.items():
        if k == "samples":
            # Never forward raw samples to the LLM.
            continue
        if k == "files_top10" and isinstance(v, list) and not allow_sensitive_evidence:
            redacted: List[Dict[str, Any]] = []
            for row in v[:10]:
                if not isinstance(row, dict):
                    continue
                redacted.append(
                    {
                        "file": "<redacted>",
                        "bad_lines": row.get("bad_lines"),
                        "first_bad_line": "<redacted>",
                    }
                )
            out[k] = redacted
            continue
        out[k] = v
    return out


def _sanitize_encoding_sample_for_llm(sample: Any, *, allow_sensitive_evidence: bool) -> Optional[Dict[str, Any]]:
    if not isinstance(sample, dict):
        return None
    # Never forward raw line previews (may contain customer data)
    out: Dict[str, Any] = {}
    for k in (
        "file",
        "line_number",
        "bad_byte_count",
        "bad_byte_positions_0_based",
        "bad_bytes_hex",
        "sec_code_bytes_50_53_ascii",
        "sec_code_utf8_chars_50_53",
    ):
        if k in sample:
            out[k] = sample.get(k)
    out.pop("preview_ascii_replace", None)

    if not allow_sensitive_evidence:
        # Hide filenames/line numbers unless explicitly allowed.
        if "file" in out:
            out["file"] = "<redacted>"
        if "line_number" in out:
            out["line_number"] = "<redacted>"
    return out


def _safe_extract_report_subset(
    report: Dict[str, Any],
    *,
    allow_sensitive_evidence: bool = False,
    include_sanitized_samples: bool = False,
    max_samples: int = 10,
) -> Dict[str, Any]:
    """
    Only pass derived/aggregated data to the LLM.
    Avoid raw ACH lines. Even though the validator may include samples, those can contain sensitive content.
    """
    sections = report.get("sections") or {}
    ach = sections.get("ach_mdv_validator") or {}
    enc = ach.get("encoding_integrity")
    enc_scrubbed = _scrub_encoding_integrity_for_llm(
        enc, allow_sensitive_evidence=allow_sensitive_evidence
    )

    # Optionally include sanitized encoding samples (NO raw previews).
    if include_sanitized_samples and isinstance(enc, dict):
        raw_samples = enc.get("samples") or []
        if isinstance(raw_samples, list):
            safe_samples: List[Dict[str, Any]] = []
            for s in raw_samples[: max(0, int(max_samples or 0))]:
                safe = _sanitize_encoding_sample_for_llm(
                    s, allow_sensitive_evidence=allow_sensitive_evidence
                )
                if safe:
                    safe_samples.append(safe)
            if isinstance(enc_scrubbed, dict):
                enc_scrubbed["samples"] = safe_samples

    subset = {
        "tenant_name": report.get("tenant_name"),
        "sid": report.get("sid"),
        "data_path": report.get("data_path") if allow_sensitive_evidence else _redact_path(report.get("data_path")),
        "run_started_at": report.get("run_started_at"),
        "run_finished_at": report.get("run_finished_at"),
        "sections": {
            "file_extension_validation": sections.get("file_extension_validation"),
            "ach_mdv_validator": {
                "totals": ach.get("totals"),
                "encoding_integrity": enc_scrubbed,
                "retail_odfi_evaluation": ach.get("retail_odfi_evaluation"),
                "type5_company_id": ach.get("type5_company_id"),
                "checks": ach.get("checks"),
                "summary": ach.get("summary"),
                "overall_status": ach.get("overall_status"),
            },
            "aba_entropy": sections.get("aba_entropy"),
            "batch_data_check": sections.get("batch_data_check"),
        },
    }
    return subset


def _normalize_ollama_base_url(s: str) -> str:
    """
    Accepts any of:
    - https://host
    - https://host/api
    - https://host/api/generate
    Normalizes to the API base URL that ends with /api.
    """
    u = (s or "").strip()
    if not u:
        return ""
    u = u.rstrip("/")
    if u.endswith("/api/generate"):
        u = u[: -len("/generate")]
    if not u.endswith("/api"):
        u = u + "/api"
    return u


def _ollama_generate(cfg: OllamaConfig, prompt: str, timeout_s: int = 180) -> str:
    """
    Uses `ollama_python` if available (matches your reference snippet).
    Falls back to raw HTTP if needed.
    """
    try:
        from ollama_python.endpoints import GenerateAPI  # type: ignore

        api = GenerateAPI(base_url=cfg.base_url, model=cfg.model)
        result = api.generate(prompt=prompt, stream=False)
        return getattr(result, "response", "") or ""
    except Exception:
        # Raw HTTP fallback
        import urllib.request

        payload = json.dumps({"model": cfg.model, "prompt": prompt, "stream": False}).encode("utf-8")
        req = urllib.request.Request(
            cfg.base_url.rstrip("/") + "/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
            return data.get("response", "")


def _agent_prompts(report_subset: Dict[str, Any]) -> Dict[str, str]:
    report_json = json.dumps(report_subset, indent=2, ensure_ascii=False)

    system_guardrails = (
        "You are analyzing outputs from deterministic ACH validation scripts.\n"
        "Do NOT invent facts that are not in the JSON.\n"
        "Do NOT request raw ACH file contents.\n"
        "When you make a claim, cite the JSON path (e.g., sections.ach_mdv_validator.totals...).\n"
        "Output must be concise and customer-friendly.\n"
    )

    prompts = {}

    prompts["analyst"] = (
        system_guardrails
        + "\nTask: Summarize validation results and failures.\n"
        + "Return JSON with keys: overall_status, key_findings[], metrics{}, evidence_paths[].\n"
        + "Input JSON:\n"
        + report_json
    )

    prompts["nacha_sme"] = (
        system_guardrails
        + "\nTask: Explain findings in NACHA terms (Type-7 addenda, returns/NOCs, SEC code alignment).\n"
        + "Return Markdown bullets with: What it means, Why it matters, Evidence.\n"
        + "Input JSON:\n"
        + report_json
    )

    prompts["remediation"] = (
        system_guardrails
        + "\nTask: Provide remediation steps for customer.\n"
        + "Return JSON with keys: priorities[], rerun_steps[], customer_questions[].\n"
        + "Input JSON:\n"
        + report_json
    )

    prompts["report_writer"] = (
        system_guardrails
        + "\nTask: Produce a customer-ready report.\n"
        + "Return Markdown with headings: Executive Summary, Key Metrics, Findings, Evidence, Next Steps.\n"
        + "Input JSON:\n"
        + report_json
    )

    return prompts


def _deterministic_markdown(report: Dict[str, Any]) -> str:
    """
    Produce a detailed summary without any model calls.
    This is used for --dry-run/--no-llm and as a fallback if Ollama is unreachable.
    """
    sections = report.get("sections") or {}
    ach = sections.get("ach_mdv_validator") or {}
    ext = sections.get("file_extension_validation") or {}
    entropy = sections.get("aba_entropy") or {}
    batch = sections.get("batch_data_check") or {}

    totals = (ach.get("totals") or {}) if isinstance(ach, dict) else {}
    enc = (ach.get("encoding_integrity") or {}) if isinstance(ach, dict) else {}
    retail = (ach.get("retail_odfi_evaluation") or {}) if isinstance(ach, dict) else {}
    checks = (ach.get("checks") or []) if isinstance(ach, dict) else []

    def _get(d: Any, k: str, default: Any = None) -> Any:
        return d.get(k, default) if isinstance(d, dict) else default

    def _status_of(sec: Any) -> str:
        if not isinstance(sec, dict):
            return "UNKNOWN"
        return str(sec.get("status") or sec.get("overall_status") or "UNKNOWN").upper()

    overall_failed = False
    for v in sections.values():
        if _status_of(v) == "FAILED":
            overall_failed = True
            break
    overall_status = "FAILED" if overall_failed else "OK"

    lines: List[str] = []
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(f"- Overall workflow status: **{overall_status}**")
    if _status_of(ext) == "FAILED":
        lines.append(f"- File extension validation failed: {int(_get(ext,'invalid_files_count',0))} invalid file(s).")
    if _status_of(batch) == "FAILED" and _get(batch, "reason"):
        lines.append(f"- Batch date completeness failed: {_get(batch, 'reason')}")
    if isinstance(retail, dict) and retail.get("result"):
        lines.append(f"- Retail ODFI indicator: **{retail.get('result')}** (reason: {retail.get('reason','')})")
    if int(_get(enc, "files_with_special_bytes", 0) or 0) > 0:
        lines.append(
            f"- Encoding integrity: **NON-ASCII/Special bytes detected** in {int(_get(enc,'files_with_special_bytes',0))} file(s)."
        )
    lines.append("")

    lines.append("## Key Metrics")
    lines.append("")
    if totals:
        lines.append(f"- Total batches (Type-5): {totals.get('batches_type5')}")
        lines.append(f"- Total transactions (Type-6): {totals.get('transactions_type6')}")
        if totals.get("records_total") is not None:
            lines.append(f"- Total records: {totals.get('records_total')}")
        if totals.get("type7_addenda_records") is not None:
            lines.append(f"- Type-7 addenda records: {totals.get('type7_addenda_records')}")
        if totals.get("799_standard_returns") is not None:
            lines.append(f"- 799 (Standard Returns): {totals.get('799_standard_returns')}")
        if totals.get("798_notifications_of_change") is not None:
            lines.append(f"- 798 (Notifications of Change): {totals.get('798_notifications_of_change')}")
    if isinstance(entropy, dict) and entropy.get("detected_ach_type"):
        lines.append(f"- ABA entropy detected type: {entropy.get('detected_ach_type')}")
    lines.append("")

    lines.append("## Findings")
    lines.append("")
    failed_checks = []
    for c in checks:
        if isinstance(c, dict) and str(c.get("status", "")).upper() == "FAILED":
            failed_checks.append(c)
    if failed_checks:
        lines.append("### ACH MDV failures")
        for c in failed_checks[:25]:
            nm = c.get("name", "<unnamed>")
            issues = c.get("issues", c.get("count", c.get("bad_count")))
            if issues is not None:
                lines.append(f"- {nm}: issues={issues}")
            else:
                lines.append(f"- {nm}")
        lines.append("")

    if int(_get(enc, "files_with_special_bytes", 0) or 0) > 0:
        lines.append("### Encoding integrity (non-ASCII / special bytes)")
        lines.append(f"- Files impacted: {int(_get(enc,'files_with_special_bytes',0))}")
        lines.append(f"- Lines impacted: {int(_get(enc,'lines_with_special_bytes',0))}")
        files_top = _get(enc, "files_top10", [])
        if isinstance(files_top, list) and files_top:
            lines.append("- Top impacted files (up to 10):")
            for row in files_top[:10]:
                if not isinstance(row, dict):
                    continue
                lines.append(
                    f"  - {row.get('file')}: bad_lines={row.get('bad_lines')}, first_bad_line={row.get('first_bad_line')}"
                )
        lines.append("")

    lines.append("## Evidence (JSON paths)")
    lines.append("")
    lines.append("- `sections.ach_mdv_validator.totals`")
    lines.append("- `sections.ach_mdv_validator.checks`")
    lines.append("- `sections.ach_mdv_validator.encoding_integrity`")
    lines.append("- `sections.ach_mdv_validator.retail_odfi_evaluation`")
    lines.append("- `sections.aba_entropy`")
    lines.append("- `sections.batch_data_check`")
    lines.append("")

    lines.append("## Next Steps")
    lines.append("")
    lines.append("- Fix upstream encoding/special-byte injection before RiskEngine ingestion if encoding integrity is flagged.")
    lines.append("- Re-run `python run_all.py <config.ini>` to regenerate `.ACH.log` + `.ACH.json`.")
    lines.append("- Generate this report from the combined JSON: `python ai_runner.py <report.ACH.json> --dry-run` (deterministic) or configure Ollama for LLM-assisted write-up.")
    lines.append("")

    return "\n".join(lines)


def run_ai_summary(
    *,
    report_json_path: str,
    out_base_path: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    dry_run: bool = False,
    allow_sensitive_evidence: bool = False,
    include_sanitized_samples: bool = False,
    max_samples: int = 10,
    timeout_s: int = 180,
) -> Tuple[str, str]:
    """
    Generates two files next to the combined report JSON:
    - <base>.ai_summary.json
    - <base>.ai_summary.md
    Returns (json_path, md_path).
    """
    report = _read_json(report_json_path)
    subset = _safe_extract_report_subset(
        report,
        allow_sensitive_evidence=allow_sensitive_evidence,
        include_sanitized_samples=include_sanitized_samples,
        max_samples=max_samples,
    )

    cfg = OllamaConfig(
        base_url=_normalize_ollama_base_url(base_url or os.environ.get("OLLAMA_BASE_URL", "").strip()),
        model=model or os.environ.get("OLLAMA_MODEL", "").strip(),
    )

    if out_base_path:
        base = out_base_path
    else:
        base = report_json_path
        if base.endswith(".json"):
            base = base[:-5]

    out_json = base + ".ai_summary.json"
    out_md = base + ".ai_summary.md"

    prompts = _agent_prompts(subset)

    started = datetime.now().isoformat(timespec="seconds")
    llm_error: Optional[str] = None
    deterministic_md = _deterministic_markdown(report)

    if dry_run:
        analyst_raw = json.dumps(
            {
                "overall_status": "DRY_RUN",
                "key_findings": ["LLM calls disabled (--dry-run/--no-llm)."],
                "metrics": {},
                "evidence_paths": [],
            }
        )
        nacha_raw = "- Dry run (no LLM).\n"
        remediation_raw = json.dumps(
            {
                "priorities": ["Review deterministic report and address any FAILED sections."],
                "rerun_steps": ["Re-run without --dry-run once Ollama is reachable."],
                "customer_questions": [],
            }
        )
        report_md = deterministic_md
    else:
        if not cfg.base_url or not cfg.model:
            llm_error = "Missing OLLAMA base URL or model (set flags or env vars). Falling back to deterministic report."
            analyst_raw = json.dumps(
                {
                    "overall_status": "LLM_UNAVAILABLE",
                    "key_findings": [llm_error],
                    "metrics": {},
                    "evidence_paths": [],
                }
            )
            nacha_raw = "- LLM unavailable; see deterministic report.\n"
            remediation_raw = json.dumps(
                {
                    "priorities": ["Configure local/on-prem Ollama if LLM summarization is desired."],
                    "rerun_steps": ["Set OLLAMA_BASE_URL and OLLAMA_MODEL, then re-run ai_runner."],
                    "customer_questions": [],
                }
            )
            report_md = deterministic_md
        else:
            try:
                analyst_raw = _ollama_generate(cfg, prompts["analyst"], timeout_s=timeout_s)
                nacha_raw = _ollama_generate(cfg, prompts["nacha_sme"], timeout_s=timeout_s)
                remediation_raw = _ollama_generate(cfg, prompts["remediation"], timeout_s=timeout_s)
                report_md = _ollama_generate(cfg, prompts["report_writer"], timeout_s=timeout_s) or ""
                if not report_md.strip():
                    report_md = deterministic_md
            except Exception as e:
                llm_error = f"LLM call failed ({type(e).__name__}): {e}. Falling back to deterministic report."
                analyst_raw = json.dumps(
                    {
                        "overall_status": "LLM_UNAVAILABLE",
                        "key_findings": [llm_error],
                        "metrics": {},
                        "evidence_paths": [],
                    }
                )
                nacha_raw = "- LLM call failed; see deterministic report.\n"
                remediation_raw = json.dumps(
                    {
                        "priorities": ["Use deterministic report for remediation until LLM endpoint is available."],
                        "rerun_steps": ["Verify DNS/network access to Ollama and re-run ai_runner."],
                        "customer_questions": [],
                    }
                )
                report_md = deterministic_md
    finished = datetime.now().isoformat(timespec="seconds")

    # Try to parse the structured agent outputs if they are JSON
    def _maybe_json(s: str) -> Any:
        try:
            return json.loads(s)
        except Exception:
            return {"raw": s}

    ai_payload = {
        "ai_summary_version": 1,
        "model": {"base_url": cfg.base_url, "model": cfg.model, "dry_run": bool(dry_run)},
        "timestamps": {"started_at": started, "finished_at": finished},
        "inputs": {"report_json_path": report_json_path},
        "llm_error": llm_error,
        "analysis": {
            "analyst": _maybe_json(analyst_raw),
            "nacha_sme": {"markdown": nacha_raw},
            "remediation": _maybe_json(remediation_raw),
        },
    }

    _write_json(out_json, ai_payload)
    _write_text(out_md, report_md)
    return out_json, out_md


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("report_json_path", help="Path to combined *.ACH.json report")
    ap.add_argument("--base-url", default=None, help="Ollama base URL (e.g. https://host/api)")
    ap.add_argument("--ollama-url", default=None, help="Alias for --base-url")
    ap.add_argument("--model", default=None)
    ap.add_argument("--out-base", default=None, help="Output base path without extension")
    ap.add_argument("--dry-run", "--no-llm", action="store_true", help="Write outputs without calling the LLM")
    ap.add_argument("--allow-sensitive-evidence", action="store_true", help="Allow filenames/line numbers in LLM input (NOT recommended)")
    ap.add_argument(
        "--include-sanitized-samples",
        action="store_true",
        help="Include validator 'encoding_integrity.samples' after removing raw previews (still derived; may include filenames/line numbers if --allow-sensitive-evidence is set).",
    )
    ap.add_argument("--max-samples", type=int, default=10, help="Max sanitized samples to include in LLM input")
    ap.add_argument("--timeout-s", type=int, default=180, help="HTTP timeout seconds for Ollama requests")
    args = ap.parse_args()

    j, m = run_ai_summary(
        report_json_path=args.report_json_path,
        out_base_path=args.out_base,
        base_url=args.base_url or args.ollama_url,
        model=args.model,
        dry_run=bool(args.dry_run),
        allow_sensitive_evidence=bool(args.allow_sensitive_evidence),
        include_sanitized_samples=bool(args.include_sanitized_samples),
        max_samples=int(args.max_samples),
        timeout_s=int(args.timeout_s),
    )
    print(j)
    print(m)

