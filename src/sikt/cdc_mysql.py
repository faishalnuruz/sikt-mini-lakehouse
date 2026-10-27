"""Real CDC: stream SIMDA's binary log into the landing zone.

This is the local equivalent of Debezium reading `mysql-bin`: the same ROW-format
binlog a connector consumes, read directly with the replication protocol. A
position file makes the stream resumable, so re-running lands nothing twice.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from decimal import Decimal

from pymysqlreplication import BinLogStreamReader
from pymysqlreplication.row_event import DeleteRowsEvent, UpdateRowsEvent, WriteRowsEvent

from sikt import landing
from sikt.config import SETTINGS
from sikt.seed_simda import connect

STATE_FILE = SETTINGS.state_dir / "mysql_cdc.json"
CDC_PREFIX = "mysql-simda"

ACTION = {WriteRowsEvent: "insert", UpdateRowsEvent: "update", DeleteRowsEvent: "delete"}


def _load_position() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"log_file": None, "log_pos": None}


def _save_position(log_file: str, log_pos: int) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"log_file": log_file, "log_pos": log_pos}, indent=2) + "\n")


def _plain(value):
    """JSON-safe conversion: binlog rows arrive as Decimal, datetime, and bytes."""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode(errors="replace")
    return value


def bootstrap_replication_privileges() -> None:
    """Binlog streaming needs REPLICATION SLAVE, which only root can grant."""
    import pymysql

    connection = pymysql.connect(
        host=SETTINGS.mysql_host,
        port=SETTINGS.mysql_port,
        user="root",
        password="sikt-root",
        autocommit=True,
    )
    with connection.cursor() as cursor:
        cursor.execute(f"GRANT REPLICATION SLAVE, REPLICATION CLIENT ON *.* TO '{SETTINGS.mysql_user}'@'%'")
    connection.close()


def stream_once() -> dict:
    """Drain the binlog to the current position, land one batch, resume from there."""
    position = _load_position()
    captured: list[dict] = []
    last_seen: tuple[str, int] | None = None

    stream = BinLogStreamReader(
        connection_settings=SETTINGS.mysql_url_args,
        server_id=910_001,
        log_file=position["log_file"],
        log_pos=position["log_pos"],
        resume_stream=position["log_file"] is not None,
        only_schemas=[SETTINGS.mysql_database],
        only_tables=["bku", "bendahara"],
        only_events=[WriteRowsEvent, UpdateRowsEvent, DeleteRowsEvent],
        # blocking=False drains everything pending, then ends the iteration:
        # exactly the semantics a scheduled incremental capture needs.
        blocking=False,
    )

    for event in stream:
        for row in event.rows:
            values = row.get("after_values", row.get("values"))
            captured.append(
                {
                    "table": event.table,
                    "action": ACTION[type(event)],
                    "values": {key: _plain(value) for key, value in values.items()},
                    "_binlog_file": stream.log_file,
                    "_binlog_pos": stream.log_pos,
                    "_captured_at": datetime.now(UTC).isoformat(),
                }
            )
        last_seen = (stream.log_file, stream.log_pos)
    stream.close()

    batches = 0
    if captured:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
        landing.write_batch(CDC_PREFIX, f"changes-{stamp}.jsonl", captured)
        batches = 1
    if last_seen:
        _save_position(*last_seen)

    return {"events": len(captured), "batches_landed": batches, "position": last_seen}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", action="store_true", help="grant replication privileges first")
    args = parser.parse_args()

    landing.ensure_bucket()
    if args.bootstrap:
        bootstrap_replication_privileges()
    connect().close()  # fail fast when the source is unreachable
    print(json.dumps(stream_once(), indent=2, default=str))


if __name__ == "__main__":
    main()
