"""Load the landing zone into the warehouse raw layer, idempotently.

Every object in the landing bucket is processed exactly once, recorded in a
manifest table inside the warehouse. Re-running the loader is free, which is
what makes the Airflow schedule safe to retrigger.

CDC records are applied as change events — upsert on the natural key for
inserts and updates, a real delete for deletes — so the raw layer mirrors the
source rather than accumulating a changelog.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

import psycopg2

from sikt import landing
from sikt.config import SETTINGS

RAW_TABLES = {
    "bku": "raw_bku",
    "bendahara": "raw_bendahara",
    "pagu_anggaran": "raw_pagu",
    "aset": "raw_aset",
}


def connect_dwh():
    return psycopg2.connect(SETTINGS.dsn(SETTINGS.dwh_database))


def ensure_dwh() -> None:
    """Create the dwh database if needed, then the raw schema and manifest."""
    bootstrap = psycopg2.connect(SETTINGS.dsn("postgres"))
    bootstrap.autocommit = True
    with bootstrap.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (SETTINGS.dwh_database,))
        if cursor.fetchone() is None:
            cursor.execute(f"CREATE DATABASE {SETTINGS.dwh_database}")
    bootstrap.close()

    connection = connect_dwh()
    with connection.cursor() as cursor:
        cursor.execute("CREATE SCHEMA IF NOT EXISTS raw")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw.pipeline_heartbeat (
                prefix    TEXT PRIMARY KEY,
                last_run  TIMESTAMPTZ NOT NULL DEFAULT now(),
                objects   INT NOT NULL DEFAULT 0,
                records   INT NOT NULL DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw.loader_manifest (
                source_key TEXT PRIMARY KEY,
                records    INT NOT NULL,
                loaded_at  TIMESTAMP NOT NULL DEFAULT now()
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw.raw_bku (
                id_bku       BIGINT PRIMARY KEY,
                kode_skpd    TEXT,
                tanggal      DATE,
                kode_akun    TEXT,
                uraian       TEXT,
                jumlah       NUMERIC(15,2),
                jenis        TEXT,
                id_bendahara INT,
                _source_key  TEXT,
                _loaded_at   TIMESTAMP DEFAULT now()
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw.raw_bendahara (
                id_bendahara INT PRIMARY KEY,
                kode_skpd    TEXT,
                nama         TEXT,
                nik          TEXT,
                no_rekening  TEXT,
                _source_key  TEXT,
                _loaded_at   TIMESTAMP DEFAULT now()
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw.raw_pagu (
                id           INT PRIMARY KEY,
                tahun        INT,
                kode_skpd    TEXT,
                kode_program TEXT,
                kode_akun    TEXT,
                pagu         NUMERIC(15,2),
                updated_at   TIMESTAMP,
                _source_key  TEXT,
                _loaded_at   TIMESTAMP DEFAULT now()
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw.raw_ref_skpd (
                kode_skpd TEXT PRIMARY KEY,
                nama_skpd  TEXT,
                _source_key TEXT,
                _loaded_at  TIMESTAMP DEFAULT now()
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw.raw_ref_program (
                kode_program TEXT PRIMARY KEY,
                nama_program TEXT,
                _source_key  TEXT,
                _loaded_at   TIMESTAMP DEFAULT now()
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS raw.raw_aset (
                kode_barang     TEXT,
                nama_barang     TEXT,
                tahun_perolehan INT,
                kode_skpd       TEXT,
                kode_akun       TEXT,
                nilai_aset      NUMERIC(15,2),
                _source_key     TEXT,
                _loaded_at      TIMESTAMP DEFAULT now()
            )
        """)
    connection.commit()
    connection.close()


def _apply(connection, record: dict, source_key: str) -> None:
    """Apply one CDC record to the raw layer as upsert or delete."""
    table = record["table"]
    action = record["action"]
    values = record["values"]

    with connection.cursor() as cursor:
        if table == "bku" and action in {"insert", "update"}:
            cursor.execute(
                """
                INSERT INTO raw.raw_bku
                    (id_bku, kode_skpd, tanggal, kode_akun, uraian, jumlah, jenis, id_bendahara, _source_key)
                VALUES (%(id_bku)s, %(kode_skpd)s, %(tanggal)s, %(kode_akun)s, %(uraian)s,
                        %(jumlah)s, %(jenis)s, %(id_bendahara)s, %(_source_key)s)
                ON CONFLICT (id_bku) DO UPDATE SET
                    kode_skpd = EXCLUDED.kode_skpd, tanggal = EXCLUDED.tanggal,
                    kode_akun = EXCLUDED.kode_akun, uraian = EXCLUDED.uraian,
                    jumlah = EXCLUDED.jumlah, jenis = EXCLUDED.jenis,
                    id_bendahara = EXCLUDED.id_bendahara, _source_key = EXCLUDED._source_key,
                    _loaded_at = now()
                """,
                {**values, "_source_key": source_key} | {"id_bku": int(values["id_bku"])},
            )
        elif table == "bku" and action == "delete":
            cursor.execute("DELETE FROM raw.raw_bku WHERE id_bku = %s", (int(values["id_bku"]),))
        elif table == "bendahara" and action in {"insert", "update"}:
            cursor.execute(
                """
                INSERT INTO raw.raw_bendahara
                    (id_bendahara, kode_skpd, nama, nik, no_rekening, _source_key)
                VALUES (%(id_bendahara)s, %(kode_skpd)s, %(nama)s, %(nik)s, %(no_rekening)s, %(_source_key)s)
                ON CONFLICT (id_bendahara) DO UPDATE SET
                    kode_skpd = EXCLUDED.kode_skpd, nama = EXCLUDED.nama,
                    nik = EXCLUDED.nik, no_rekening = EXCLUDED.no_rekening,
                    _source_key = EXCLUDED._source_key, _loaded_at = now()
                """,
                {**values, "_source_key": source_key} | {"id_bendahara": int(values["id_bendahara"])},
            )
        elif table == "bendahara" and action == "delete":
            cursor.execute(
                "DELETE FROM raw.raw_bendahara WHERE id_bendahara = %s", (int(values["id_bendahara"]),)
            )
        elif table == "pagu_anggaran" and action in {"insert", "update"}:
            cursor.execute(
                """
                INSERT INTO raw.raw_pagu
                    (id, tahun, kode_skpd, kode_program, kode_akun, pagu, updated_at, _source_key)
                VALUES (%(id)s, %(tahun)s, %(kode_skpd)s, %(kode_program)s, %(kode_akun)s,
                        %(pagu)s, %(updated_at)s, %(_source_key)s)
                ON CONFLICT (id) DO UPDATE SET
                    tahun = EXCLUDED.tahun, kode_skpd = EXCLUDED.kode_skpd,
                    kode_program = EXCLUDED.kode_program, kode_akun = EXCLUDED.kode_akun,
                    pagu = EXCLUDED.pagu, updated_at = EXCLUDED.updated_at,
                    _source_key = EXCLUDED._source_key, _loaded_at = now()
                """,
                {**values, "_source_key": source_key} | {"id": int(values["id"])},
            )
        elif table == "pagu_anggaran" and action == "delete":
            cursor.execute("DELETE FROM raw.raw_pagu WHERE id = %s", (int(values["id"]),))


def load() -> dict:
    """Process every un-landed object exactly once."""
    ensure_dwh()
    connection = connect_dwh()

    with connection.cursor() as cursor:
        cursor.execute("SELECT source_key FROM raw.loader_manifest")
        already = {row[0] for row in cursor.fetchall()}

    processed, skipped, applied = [], [], 0
    for prefix in ("mysql-simda", "pg-ebudget", "oracle-aset", "references"):
        for key in landing.list_objects(prefix):
            if key in already:
                skipped.append(key)
                continue
            records = landing.read_object(key)

            if prefix == "references":
                table = "raw_ref_skpd" if "ref-skpd" in key else "raw_ref_program"
                key_column = "kode_skpd" if table == "raw_ref_skpd" else "kode_program"
                name_column = "nama_skpd" if table == "raw_ref_skpd" else "nama_program"
                with connection.cursor() as cursor:
                    for row in records:
                        cursor.execute(
                            f"""
                            INSERT INTO raw.{table} ({key_column}, {name_column}, _source_key)
                            VALUES (%s, %s, %s)
                            ON CONFLICT ({key_column}) DO UPDATE SET
                                {name_column} = EXCLUDED.{name_column},
                                _source_key = EXCLUDED._source_key, _loaded_at = now()
                            """,
                            (row[key_column], row[name_column], key),
                        )
                        applied += 1
            elif prefix == "oracle-aset":
                with connection.cursor() as cursor:
                    page = [
                        (
                            row["kode_barang"], row["nama_barang"], int(row["tahun_perolehan"]),
                            row["kode_skpd"], row["kode_akun"], row["nilai_aset"], key,
                        )
                        for row in records
                    ]
                    cursor.executemany(
                        """
                        INSERT INTO raw.raw_aset
                            (kode_barang, nama_barang, tahun_perolehan, kode_skpd, kode_akun, nilai_aset, _source_key)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        page,
                    )
                applied += len(records)
            else:
                for record in records:
                    _apply(connection, record, key)
                    applied += 1

            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO raw.loader_manifest (source_key, records)
                    VALUES (%s, %s)
                    ON CONFLICT (source_key) DO NOTHING
                    """,
                    (key, len(records)),
                )
            connection.commit()
            processed.append({"key": key, "records": len(records)})

    # A heartbeat per prefix, written whether or not anything was pending:
    # freshness is "did the pipeline run", not "did this table change".
    per_prefix: dict[str, dict] = {prefix: {"objects": 0, "records": 0} for prefix in
                                  ("mysql-simda", "pg-ebudget", "oracle-aset", "references")}
    for entry in processed:
        prefix = entry["key"].split("/", 1)[0]
        per_prefix.setdefault(prefix, {"objects": 0, "records": 0})
        per_prefix[prefix]["objects"] += 1
        per_prefix[prefix]["records"] += entry["records"]

    with connection.cursor() as cursor:
        for prefix, totals in per_prefix.items():
            cursor.execute(
                """
                INSERT INTO raw.pipeline_heartbeat (prefix, last_run, objects, records)
                VALUES (%s, now(), %s, %s)
                ON CONFLICT (prefix) DO UPDATE SET
                    last_run = now(), objects = EXCLUDED.objects, records = EXCLUDED.records
                """,
                (prefix, totals["objects"], totals["records"]),
            )
    connection.commit()
    connection.close()
    return {
        "objects_processed": len(processed),
        "objects_skipped": len(skipped),
        "records_applied": applied,
        "details": processed,
        "loaded_at": datetime.now(UTC).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    print(json.dumps(load(), indent=2))


if __name__ == "__main__":
    main()
