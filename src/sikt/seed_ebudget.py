"""Seed e-budgeting (PostgreSQL) and the Oracle Aset file drop.

The pagu table is the budget side of the story; realization comes from SIMDA's
BKU. The Aset extract is a nightly CSV export, which is how the legacy Oracle
system actually arrives in an integration project — labelled honestly rather
than pretending there is a local Oracle.
"""

from __future__ import annotations

import argparse
import csv
import json
import random

import psycopg2

from sikt import landing, targets
from sikt.config import SETTINGS

ASET_ROWS = 400


def connect(database: str):
    return psycopg2.connect(SETTINGS.dsn(database))


def create_schema(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS pagu_anggaran")
        cursor.execute("DROP TABLE IF EXISTS ref_program")
        cursor.execute("DROP TABLE IF EXISTS ref_skpd")
        cursor.execute("""
            CREATE TABLE ref_skpd (
                kode_skpd VARCHAR(12) PRIMARY KEY,
                nama_skpd  VARCHAR(120) NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE ref_program (
                kode_program VARCHAR(12) PRIMARY KEY,
                nama_program VARCHAR(120) NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE pagu_anggaran (
                id           SERIAL PRIMARY KEY,
                tahun        INT NOT NULL,
                kode_skpd    VARCHAR(12) NOT NULL,
                kode_program VARCHAR(12) NOT NULL,
                kode_akun    VARCHAR(10) NOT NULL,
                pagu         DECIMAL(15,2) NOT NULL,
                updated_at   TIMESTAMP NOT NULL DEFAULT now()
            )
        """)


def seed(connection, seed_value: int = 7) -> dict:
    rng = random.Random(seed_value)
    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE ref_skpd, ref_program, pagu_anggaran")
        cursor.executemany(
            "INSERT INTO ref_skpd (kode_skpd, nama_skpd) VALUES (%s, %s)",
            [(kode, nama) for kode, nama, _, _ in targets.SKPDS],
        )
        programs = {
            kode: program for pair in targets.PROGRAMS.values() for kode, program in [(p[0], p[1]) for p in pair]
        }
        programs = {}
        for pair in targets.PROGRAMS.values():
            for kode_program, nama_program in pair:
                programs[kode_program] = (kode_program, nama_program)
        cursor.executemany(
            "INSERT INTO ref_program (kode_program, nama_program) VALUES (%s, %s)",
            sorted(programs.values()),
        )

        rows = 0
        for kode, nama, pagu, _ in targets.SKPDS:
            entries = targets.PROGRAMS[kode]
            weights = [rng.uniform(0.3, 1.0) for _ in entries]
            scale = pagu / sum(weights)
            for (kode_program, _), weight in zip(entries, weights):
                # split each program's pagu across two expenditure accounts
                for share, akun in ((0.62, targets.AKUN_BELANJA[0]), (0.38, targets.AKUN_BELANJA[1])):
                    cursor.execute(
                        """
                        INSERT INTO pagu_anggaran (tahun, kode_skpd, kode_program, kode_akun, pagu)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            targets.TAHUN_ANGGARAN,
                            kode,
                            kode_program,
                            akun,
                            round(weight * scale * share, 2),
                        ),
                    )
                    rows += 1
    connection.commit()
    return {"ref_skpd": len(targets.SKPDS), "ref_program": len(programs), "pagu_anggaran": rows}


def seed_aset(seed_value: int = 7) -> dict:
    """Write the nightly Aset export: the one source that arrives as a file."""
    rng = random.Random(seed_value + 1)
    path = landing.local_batch_path("aset_extract_2026-10-24.csv")
    barang = ("Kendaraan Dinas Operasional", "Server Rak", "Laptop Kerja", "Meja Kerja", "Genset", "Mobil Ambulans")
    rows = 0
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["kode_barang", "nama_barang", "tahun_perolehan", "kode_skpd", "kode_akun", "nilai_aset"])
        for kode, _, _, _ in targets.SKPDS:
            for _ in range(ASET_ROWS // len(targets.SKPDS)):
                writer.writerow(
                    [
                        f"AST-{rng.randint(10_000, 99_999)}",
                        rng.choice(barang),
                        rng.randint(2015, 2025),
                        kode,
                        "524114",
                        round(rng.uniform(5e6, 2.5e9), 2),
                    ]
                )
                rows += 1
    return {"aset_rows": rows, "path": str(path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    connection = connect(SETTINGS.ebudget_database)

    # The slot must exist before the first seed lands, so that the initial load
    # itself is captured — the same behaviour as a Debezium snapshot.
    from sikt.cdc_pg import ensure_slot

    ensure_slot(connection)

    create_schema(connection)
    summary = seed(connection, seed_value=args.seed)
    connection.close()

    summary.update(seed_aset(args.seed))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
