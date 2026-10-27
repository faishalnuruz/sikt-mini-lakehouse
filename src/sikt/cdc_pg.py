"""Real CDC: consume the e-budgeting logical replication slot.

PostgreSQL's logical replication is the same mechanism Debezium builds on. Here
the built-in `test_decoding` plugin feeds a slot, and the consumer drains it
with `pg_logical_slot_get_changes` — the batch-drain form of what a connector
streams continuously in production. Once changes are consumed they are gone
from the slot, so re-running captures nothing twice.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime

import psycopg2

from sikt import landing
from sikt.config import SETTINGS

SLOT_NAME = "sikt_ebudget_cdc"
CDC_PREFIX = "pg-ebudget"

# test_decoding line: `table public.pagu_anggaran: INSERT: id[integer]:12 tahun[integer]:2026 kode_skpd[text]:'1.01.02' ...`
LINE = re.compile(r"^table public\.(\w+): (INSERT|UPDATE|DELETE): (.*)$")
COLUMN = re.compile(r"(\w+)\[[^\]]*\]:(?:'((?:''|[^'])*)'|(\S+))")


def ensure_slot(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_replication_slots WHERE slot_name = %s", (SLOT_NAME,))
        if cursor.fetchone() is None:
            cursor.execute("SELECT * FROM pg_create_logical_replication_slot(%s, 'test_decoding')", (SLOT_NAME,))
    connection.commit()


def parse_line(raw: str) -> dict | None:
    """Turn one test_decoding line into a change record, or None for noise."""
    match = LINE.match(raw)
    if not match:
        return None
    table, action, remainder = match.groups()
    values = {}
    for column in COLUMN.finditer(remainder):
        name, quoted, plain = column.group(1), column.group(2), column.group(3)
        if quoted is not None:
            values[name] = quoted.replace("''", "'")
        else:
            # `findall` flattens non-participating groups to ''; `finditer` keeps
            # them distinct, which is what makes quoted vs unquoted parseable.
            values[name] = None if plain == "null" else plain
    record = {"table": table, "action": action.lower(), "values": values}
    if action == "UPDATE" and "old-key" in remainder:
        record["note"] = "key changed"
    return record


def drain_once() -> dict:
    connection = psycopg2.connect(SETTINGS.dsn(SETTINGS.ebudget_database))
    ensure_slot(connection)
    captured: list[dict] = []

    with connection.cursor() as cursor:
        cursor.execute("SELECT lsn::text, xid::text, data FROM pg_logical_slot_get_changes(%s, NULL, NULL)", (SLOT_NAME,))
        for lsn, xid, raw in cursor.fetchall():
            record = parse_line(raw) if raw else None
            if record is None:
                continue
            record.update({"_lsn": lsn, "_xid": xid, "_captured_at": datetime.now(UTC).isoformat()})
            captured.append(record)
    connection.commit()
    connection.close()

    batches = 0
    if captured:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        landing.write_batch(CDC_PREFIX, f"changes-{stamp}.jsonl", captured)
        batches = 1

    return {"events": len(captured), "batches_landed": batches, "slot": SLOT_NAME}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    landing.ensure_bucket()
    print(json.dumps(drain_once(), indent=2))


if __name__ == "__main__":
    main()
