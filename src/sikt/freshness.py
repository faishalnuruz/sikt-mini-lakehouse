"""The freshness gate: has each source been ingested within the SLA?

dbt's source freshness measures when rows landed, which makes a rarely-changing
table look stale even when the pipeline is healthy. The operationally correct
question is whether the loader ran for each source — so the loader writes a
heartbeat per prefix on every run, and this check fails the DAG when any source
misses its SLA. That is the same reasoning behind `source freshness` in dbt,
applied to the object that actually represents the pipeline run.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from sikt.loader import connect_dwh, ensure_dwh

EXPECTED_PREFIXES = ("mysql-simda", "pg-ebudget", "oracle-aset", "references")


def check(max_age_hours: float = 2.0) -> dict:
    ensure_dwh()
    connection = connect_dwh()
    with connection.cursor() as cursor:
        cursor.execute("SELECT prefix, last_run FROM raw.pipeline_heartbeat")
        recorded = {row[0]: row[1] for row in cursor.fetchall()}
    connection.close()

    now = datetime.now(UTC)
    results = {}
    for prefix in EXPECTED_PREFIXES:
        last_run = recorded.get(prefix)
        if last_run is not None and last_run.tzinfo is None:
            # a naive timestamp from the database is UTC by construction here
            last_run = last_run.replace(tzinfo=UTC)
        age_hours = (now - last_run).total_seconds() / 3600 if last_run else None
        results[prefix] = {
            "last_run": last_run.isoformat() if last_run else None,
            "age_hours": round(age_hours, 2) if age_hours is not None else None,
            "within_sla": age_hours is not None and age_hours <= max_age_hours,
        }
    return {"sla_hours": max_age_hours, "sources": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-age-hours", type=float, default=2.0)
    args = parser.parse_args()

    report = check(max_age_hours=args.max_age_hours)
    for prefix, source in report["sources"].items():
        status = "ok" if source["within_sla"] else "STALE"
        age = f"{source['age_hours']}h" if source["age_hours"] is not None else "never ingested"
        print(f"  {prefix:14} {status:6} last run {age}")

    if all(source["within_sla"] for source in report["sources"].values()):
        print(json.dumps({"freshness": "pass"}))
        return 0
    print(json.dumps({"freshness": "fail", "detail": report}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
