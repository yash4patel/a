import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass
class RulesetLoadResult:
    ruleset: Optional[Dict[str, Any]]
    source: str
    ruleset_name: str
    error: Optional[str] = None


def _read_json_file(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return default


def load_metadata_ruleset(config, logger) -> Optional[Dict[str, Any]]:
    """
    Loads a workflow ruleset (metadata) from either:
    - MySQL (preferred for "metadata stored in SQL")
    - Local JSON file (fallback)

    The result is a dict that can:
    - enable/disable sections
    - override parameters (e.g., sec_codes, max_error_percent, etc.)
    - enable/disable individual ACH MDV checks
    """
    enabled = bool(getattr(config, "metadata_enabled", False))
    if not enabled:
        return None

    source = (getattr(config, "metadata_source", "") or "mysql").strip().lower()
    name = (getattr(config, "metadata_ruleset_name", "") or "default").strip()
    try:
        if source in ("file", "local", "json"):
            path = (getattr(config, "metadata_json_path", "") or "").strip()
            if not path:
                raise ValueError("metadata_json_path is blank")
            if not os.path.isabs(path):
                # relative to repo cwd
                path = os.path.join(os.getcwd(), path)
            rs = _read_json_file(path)
            return {"ruleset_name": name, "rules": rs, "source": f"file:{path}"}

        # default: mysql
        rs = load_ruleset_from_mysql(config=config, ruleset_name=name)
        # Keep a stable wrapper shape for downstream code
        if isinstance(rs, dict) and "rules" in rs:
            rs.setdefault("source", "mysql")
            return rs
        return {"ruleset_name": name, "rules": rs, "source": "mysql"}
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        if logger:
            logger.warning(f"Metadata ruleset load failed ({source}): {msg}")
        return None


def load_ruleset_from_mysql(*, config, ruleset_name: str) -> Dict[str, Any]:
    """
    MySQL table layout (default):
      CREATE TABLE validation_ruleset (
        ruleset_name VARCHAR(128) PRIMARY KEY,
        version INT NOT NULL,
        rules_json JSON NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
      );
    """
    host = (getattr(config, "metadata_mysql_host", "") or "").strip()
    user = (getattr(config, "metadata_mysql_user", "") or "").strip()
    password = (getattr(config, "metadata_mysql_password", "") or "").strip()
    database = (getattr(config, "metadata_mysql_database", "") or "").strip()
    table = (getattr(config, "metadata_mysql_table", "") or "validation_ruleset").strip()
    if not host or not user or not database:
        raise ValueError("Missing metadata MySQL connection config (host/user/database)")

    try:
        import mysql.connector  # type: ignore
    except Exception as e:
        raise RuntimeError(
            f"mysql-connector-python not installed/available: {e}"
        ) from e

    cnx = mysql.connector.connect(host=host, user=user, password=password, database=database)
    try:
        cur = cnx.cursor()
        cur.execute(
            f"SELECT rules_json FROM `{table}` WHERE ruleset_name = %s LIMIT 1",
            (ruleset_name,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"No ruleset found in {database}.{table} for ruleset_name={ruleset_name!r}")
        raw = row[0]
        # mysql connector may return dict already or string
        if isinstance(raw, (dict, list)):
            return {"ruleset_name": ruleset_name, "rules": raw}
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", "replace")
        rules = json.loads(raw)
        return {"ruleset_name": ruleset_name, "rules": rules}
    finally:
        try:
            cur.close()
        except Exception:
            pass
        cnx.close()


def _unwrap_ruleset(ruleset: Dict[str, Any]) -> Dict[str, Any]:
    # Support both shapes:
    # - {"ruleset_name": "...", "rules": {...}}
    # - {...} (rules directly)
    if isinstance(ruleset.get("rules"), dict):
        return ruleset["rules"]
    return ruleset


def get_section_enabled(
    ruleset: Optional[Dict[str, Any]], section_id: str, *, default: bool = True
) -> bool:
    if not ruleset:
        return default
    rs = _unwrap_ruleset(ruleset)
    workflow = rs.get("workflow") if isinstance(rs, dict) else None
    sections = (workflow or {}).get("sections") if isinstance(workflow, dict) else None
    if not isinstance(sections, list):
        return default
    for s in sections:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or "").strip()
        if sid == section_id:
            return _parse_bool(s.get("enabled"), default)
    return default


def get_enabled_sections(ruleset: Optional[Dict[str, Any]]) -> Optional[Dict[str, bool]]:
    if not ruleset:
        return None
    rs = _unwrap_ruleset(ruleset)
    workflow = rs.get("workflow") if isinstance(rs, dict) else None
    sections = (workflow or {}).get("sections") if isinstance(workflow, dict) else None
    if not isinstance(sections, list):
        return None
    out: Dict[str, bool] = {}
    for s in sections:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or "").strip()
        if not sid:
            continue
        out[sid] = _parse_bool(s.get("enabled"), True)
    return out or None


def apply_config_overrides(config, ruleset: Optional[Dict[str, Any]]) -> None:
    """
    Apply parameter overrides and check enablement flags onto the Config object
    before running validators.
    """
    if not ruleset:
        return
    rs = _unwrap_ruleset(ruleset)
    if not isinstance(rs, dict):
        return

    ach = rs.get("ach_mdv_validator")
    if isinstance(ach, dict):
        # params
        if "max_error_percent" in ach:
            try:
                config.max_error_percent = float(ach.get("max_error_percent"))
            except Exception:
                pass
        if isinstance(ach.get("sec_codes"), list):
            config.sec_codes = [str(x).strip() for x in ach.get("sec_codes") if str(x).strip()]
        if "show_problem_lines" in ach:
            try:
                config.show_problem_lines = bool(ach.get("show_problem_lines"))
            except Exception:
                pass
        if "problem_line_limit" in ach:
            try:
                config.problem_line_limit = int(ach.get("problem_line_limit"))
            except Exception:
                pass

        # enable/disable mdv checks
        checks_cfg = ach.get("checks")
        if isinstance(checks_cfg, dict):
            mdv_enabled: Dict[str, bool] = {}
            for check_name, c in checks_cfg.items():
                if isinstance(c, dict) and "enabled" in c:
                    mdv_enabled[str(check_name)] = _parse_bool(c.get("enabled"), True)
            if mdv_enabled:
                setattr(config, "mdv_checks_enabled", mdv_enabled)

    batch = rs.get("batch_data_check")
    if isinstance(batch, dict):
        # allow overriding required_days by type
        req = batch.get("required_days_by_type")
        if isinstance(req, dict):
            if "ODFI" in req:
                try:
                    config.batch_needed_days_odfi = int(req.get("ODFI"))
                except Exception:
                    pass
            if "RDFI" in req:
                try:
                    config.batch_needed_days_rdfi = int(req.get("RDFI"))
                except Exception:
                    pass
        if "record_type_to_count" in batch:
            try:
                config.batch_record_type_to_count = int(batch.get("record_type_to_count"))
            except Exception:
                pass


def apply_ruleset_to_config(*, config, ruleset: Optional[Dict[str, Any]]) -> None:
    # Backward-compatible alias
    apply_config_overrides(config, ruleset)


def apply_config_overrides_compat(*, config, ruleset: Optional[Dict[str, Any]]) -> None:
    # Another alias for older imports (if any)
    apply_config_overrides(config, ruleset)


def apply_config_overrides_to_config(*, config, ruleset: Optional[Dict[str, Any]]) -> None:
    apply_config_overrides(config, ruleset)


def apply_ruleset_to_reports(*, workflow_report: Dict[str, Any], ruleset: Optional[Dict[str, Any]]) -> None:
    """
    Post-process section reports with metadata context (non-invasive).
    """
    if not ruleset or not isinstance(workflow_report, dict):
        return
    rs = _unwrap_ruleset(ruleset)
    workflow_report.setdefault("metadata", {})
    workflow_report["metadata"]["ruleset"] = rs.get("ruleset_name") if isinstance(ruleset.get("ruleset_name"), str) else ruleset.get("ruleset_name")
    workflow_report["metadata"]["metadata_enabled"] = True

