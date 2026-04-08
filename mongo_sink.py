import json
import os
from datetime import datetime
from typing import Any, Dict, Optional


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _get_env_or(cfg: Any, key: str, default: str = "") -> str:
    if isinstance(cfg, dict):
        v = cfg.get(key)
    else:
        v = getattr(cfg, key, None)
    if v is None or str(v).strip() == "":
        return os.environ.get(key.upper(), default).strip()
    return str(v).strip()


def _mongo_client(mongo_uri: str):
    # Lazy import so base workflow can run without pymongo installed.
    from pymongo import MongoClient  # type: ignore

    return MongoClient(mongo_uri)


def insert_workflow_report_to_mongo(
    *,
    workflow_report: Dict[str, Any],
    mongo_uri: str,
    database: str,
    collection: str,
    logger=None,
) -> Optional[str]:
    """
    Store the combined workflow JSON output as a single MongoDB document.
    Returns inserted_id as string.
    """
    try:
        client = _mongo_client(mongo_uri)
        db = client[database]
        coll = db[collection]
        doc = dict(workflow_report)
        doc.setdefault("ingested_at", _now_iso())
        res = coll.insert_one(doc)
        inserted_id = str(res.inserted_id)
        if logger:
            logger.info(f"MongoDB: inserted workflow report into {database}.{collection} _id={inserted_id}")
        return inserted_id
    except Exception as e:
        if logger:
            logger.warning(f"MongoDB write skipped/failed: {e}")
        return None


def maybe_write_to_mongo(*, workflow_report: Dict[str, Any], config, logger=None) -> Optional[str]:
    """
    Optional sink: write the combined workflow JSON into MongoDB when enabled in config.
    Config keys (and env var fallbacks):
    - mongo_enabled (MONGO_ENABLED)
    - mongo_uri (MONGO_URI)
    - mongo_database (MONGO_DATABASE)
    - mongo_collection (MONGO_COLLECTION)
    """
    enabled = False
    try:
        if isinstance(config, dict):
            enabled = bool(config.get("mongo_enabled", False))
        else:
            enabled = bool(getattr(config, "mongo_enabled", False))
    except Exception:
        enabled = False

    if not enabled:
        return None

    mongo_uri = _get_env_or(config, "mongo_uri", "")
    database = _get_env_or(config, "mongo_database", "ps_validation")
    collection = _get_env_or(config, "mongo_collection", "workflow_reports")

    if not mongo_uri:
        if logger:
            logger.warning("MongoDB enabled but mongo_uri is missing (set mongo_uri or MONGO_URI).")
        return None

    return insert_workflow_report_to_mongo(
        workflow_report=workflow_report,
        mongo_uri=mongo_uri,
        database=database,
        collection=collection,
        logger=logger,
    )


# Backwards-compatible alias used by run_all.py
def maybe_write_workflow_to_mongo(*, workflow_report: Dict[str, Any], config, logger=None) -> Optional[str]:
    return maybe_write_to_mongo(workflow_report=workflow_report, config=config, logger=logger)

