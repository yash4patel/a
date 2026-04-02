import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


def _parse_iso_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Accept "YYYY-MM-DDTHH:MM:SS"
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _flatten_ach_subchecks(report: Dict[str, Any]) -> List[Tuple[str, str, Dict[str, Any]]]:
    """
    Returns list of (validation_key, status, payload) for ACH MDV sub-checks.
    """
    out: List[Tuple[str, str, Dict[str, Any]]] = []
    ach = (report.get("sections") or {}).get("ach_mdv_validator") or {}
    checks = ach.get("checks") or []
    for chk in checks:
        name = str(chk.get("name") or "").strip()
        if not name:
            continue
        key = (
            "ach."
            + name.lower()
            .replace("(", "")
            .replace(")", "")
            .replace("/", "_")
            .replace("-", "_")
            .replace(" ", "_")
            .replace("__", "_")
        )
        status = str(chk.get("status") or "INFO").upper()
        out.append((key, status, chk))
    return out


def ensure_tables_mysql(cnx, schema: str = "ps_auto") -> None:
    """
    Create minimal tables for storing full run artifacts and per-validation payloads.
    Idempotent.
    """
    cur = cnx.cursor()
    cur.execute(f"USE `{schema}`")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS validation_run (
          id BIGINT PRIMARY KEY AUTO_INCREMENT,
          tenant_name VARCHAR(128),
          sid VARCHAR(64),
          data_path TEXT,
          log_file_path TEXT,
          json_file_path TEXT,
          started_at DATETIME NULL,
          finished_at DATETIME NULL,
          status VARCHAR(16),
          report_json JSON NOT NULL,
          log_text LONGTEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS validation_result (
          run_id BIGINT NOT NULL,
          validation_key VARCHAR(128) NOT NULL,
          status VARCHAR(16) NOT NULL,
          payload JSON NOT NULL,
          PRIMARY KEY (run_id, validation_key),
          CONSTRAINT fk_validation_result_run
            FOREIGN KEY (run_id) REFERENCES validation_run(id)
            ON DELETE CASCADE
        )
        """
    )

    cnx.commit()
    cur.close()


def insert_run_and_results_mysql(
    *,
    host: str,
    user: str,
    password: str,
    schema: str,
    report: Dict[str, Any],
    log_path: str,
    ensure_tables: bool = True,
) -> int:
    """
    Inserts:
    - 1 row in validation_run: full report JSON + full log text
    - N rows in validation_result: each report section + each ACH sub-check
    Returns run_id.
    """
    import mysql.connector  # type: ignore

    cnx = mysql.connector.connect(host=host, user=user, password=password, database=schema)
    try:
        if ensure_tables:
            ensure_tables_mysql(cnx, schema=schema)

        cur = cnx.cursor()

        tenant_name = report.get("tenant_name")
        sid = report.get("sid")
        data_path = report.get("data_path")
        started = _parse_iso_dt(report.get("run_started_at"))
        finished = _parse_iso_dt(report.get("run_finished_at"))
        log_text = _read_text(log_path)

        # overall status: FAILED if any section FAILED
        status = "OK"
        for sec in (report.get("sections") or {}).values():
            if isinstance(sec, dict) and str(sec.get("status", "")).upper() == "FAILED":
                status = "FAILED"
                break

        cur.execute(
            """
            INSERT INTO validation_run
              (tenant_name, sid, data_path, log_file_path, json_file_path, started_at, finished_at, status, report_json, log_text)
            VALUES
              (%s,%s,%s,%s,%s,%s,%s,%s,CAST(%s AS JSON),%s)
            """,
            (
                tenant_name,
                sid,
                data_path,
                report.get("log_file"),
                report.get("json_file"),
                started.strftime("%Y-%m-%d %H:%M:%S") if started else None,
                finished.strftime("%Y-%m-%d %H:%M:%S") if finished else None,
                status,
                _json_dumps(report),
                log_text,
            ),
        )
        run_id = cur.lastrowid

        # Insert each section
        sections = report.get("sections") or {}
        for key, payload in sections.items():
            if not isinstance(payload, dict):
                payload = {"value": payload}
            sec_status = str(payload.get("status") or payload.get("overall_status") or "INFO").upper()
            cur.execute(
                """
                INSERT INTO validation_result (run_id, validation_key, status, payload)
                VALUES (%s,%s,%s,CAST(%s AS JSON))
                ON DUPLICATE KEY UPDATE status=VALUES(status), payload=VALUES(payload)
                """,
                (run_id, str(key), sec_status, _json_dumps(payload)),
            )

        # Insert each ACH sub-check (from ach_mdv_validator.checks[])
        for vkey, vstatus, vpayload in _flatten_ach_subchecks(report):
            cur.execute(
                """
                INSERT INTO validation_result (run_id, validation_key, status, payload)
                VALUES (%s,%s,%s,CAST(%s AS JSON))
                ON DUPLICATE KEY UPDATE status=VALUES(status), payload=VALUES(payload)
                """,
                (run_id, vkey, vstatus, _json_dumps(vpayload)),
            )

        cnx.commit()
        cur.close()
        return int(run_id)
    finally:
        cnx.close()


def maybe_write_to_mysql(*, workflow_report: Dict[str, Any], log_path: str, logger) -> Optional[int]:
    """
    Optional sink to persist the full run output into MySQL.
    Enabled when MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE are set.

    Env vars:
    - MYSQL_HOST
    - MYSQL_USER
    - MYSQL_PASSWORD
    - MYSQL_DATABASE (schema name, e.g. ps_auto)
    - MYSQL_ENSURE_TABLES (default true)
    """
    host = os.environ.get("MYSQL_HOST", "").strip()
    user = os.environ.get("MYSQL_USER", "").strip()
    password = os.environ.get("MYSQL_PASSWORD", "").strip()
    schema = os.environ.get("MYSQL_DATABASE", "").strip()
    ensure_tables = os.environ.get("MYSQL_ENSURE_TABLES", "true").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )

    if not host and not user and not schema:
        # Not configured
        return None

    missing = [k for k, v in [("MYSQL_HOST", host), ("MYSQL_USER", user), ("MYSQL_PASSWORD", password), ("MYSQL_DATABASE", schema)] if not v]
    if missing:
        logger.error(f"MySQL output requested but missing env vars: {', '.join(missing)}")
        return None

    try:
        run_id = insert_run_and_results_mysql(
            host=host,
            user=user,
            password=password,
            schema=schema,
            report=workflow_report,
            log_path=log_path,
            ensure_tables=ensure_tables,
        )
        logger.info(f"MySQL output saved (run_id={run_id})")
        return run_id
    except Exception as e:
        logger.error(f"MySQL write failed: {e}")
        return None

