"""Grant the BI role exactly what it needs — and nothing more.

`analyst_sikt` may read every dbt-built schema (staging, intermediate, marts)
but has no grant on the raw schema, where NIKs and account numbers still live.
That is the local form of the PRD's RBAC requirement: Metabase connects as this
role, so the raw layer is structurally out of reach for reporting users.
"""

from __future__ import annotations

import argparse
import json

from sikt.loader import connect_dwh, ensure_dwh

BI_ROLE = "analyst_sikt"


def grant() -> dict:
    ensure_dwh()
    connection = connect_dwh()
    with connection.cursor() as cursor:
        cursor.execute(f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{BI_ROLE}') THEN CREATE ROLE {BI_ROLE} NOLOGIN; END IF; END $$")
        for schema in ("analytics_staging", "analytics_intermediate", "analytics_marts"):
            cursor.execute(f"GRANT USAGE ON SCHEMA {schema} TO {BI_ROLE}")
            cursor.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {BI_ROLE}")
        # raw is intentionally absent: no grant means no access.
        cursor.execute("SELECT count(*) FROM information_schema.role_table_grants WHERE grantee = %s AND table_schema = 'raw'", (BI_ROLE,))
        raw_grants = cursor.fetchone()[0]
    connection.commit()
    connection.close()
    return {"role": BI_ROLE, "schemas_readable": ["analytics_staging", "analytics_intermediate", "analytics_marts"], "raw_tables_visible": raw_grants}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    print(json.dumps(grant(), indent=2))


if __name__ == "__main__":
    main()
