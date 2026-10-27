"""Seed SIMDA (MySQL): SKPD reference, treasury staff with real-looking PII,
and a BKU ledger whose totals drive the realization story.

The BKU is the Buku Kas Umum — the cash ledger every treasurer enters spending
into. Its rows are exactly what the binary log carries out in the CDC demo, and
their totals are what the >90% alert is computed from.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import date, timedelta

import pymysql

from sikt import landing, targets

URAIAN = (
    "Pembayaran honor tenaga pendukung {bulan}",
    "Belanja alat tulis kantor {bulan}",
    "Pembayaran jasa kebersihan {bulan}",
    "Belanja perjalanan dinas {bulan}",
    "Pembayaran kontrak {program} {bulan}",
    "Belanja pemeliharaan {program} {bulan}",
    "Transfer bantuan sosial {bulan}",
    "Belanja barang pakai habis {bulan}",
)
BULAN = {8: "Agustus", 9: "September", 10: "Oktober"}


def _nik(rng: random.Random, index: int) -> str:
    """Deterministic, obviously fake 16-digit NIKs: PII for the masking demo."""
    return f"317{rng.randint(100000000000, 999999999999)}{index % 10}"


def connect() -> pymysql.Connection:
    from sikt.config import SETTINGS

    return pymysql.connect(**SETTINGS.mysql_url_args, autocommit=True)


def create_schema(connection: pymysql.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS bku")
        cursor.execute("DROP TABLE IF EXISTS bendahara")
        cursor.execute("DROP TABLE IF EXISTS ref_skpd")
        cursor.execute("""
            CREATE TABLE ref_skpd (
                kode_skpd VARCHAR(12) PRIMARY KEY,
                nama_skpd  VARCHAR(120) NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE bendahara (
                id_bendahara INT PRIMARY KEY AUTO_INCREMENT,
                kode_skpd    VARCHAR(12) NOT NULL,
                nama         VARCHAR(80) NOT NULL,
                nik          CHAR(16) NOT NULL,
                no_rekening  VARCHAR(24) NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE bku (
                id_bku       BIGINT PRIMARY KEY AUTO_INCREMENT,
                kode_skpd    VARCHAR(12) NOT NULL,
                tanggal      DATE NOT NULL,
                kode_akun    VARCHAR(10) NOT NULL,
                uraian       VARCHAR(160) NOT NULL,
                jumlah       DECIMAL(15,2) NOT NULL,
                jenis        ENUM('PENGELUARAN','PENERIMAAN') NOT NULL,
                id_bendahara INT NOT NULL,
                created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)


def seed(connection: pymysql.Connection, seed_value: int = 7) -> dict:
    rng = random.Random(seed_value)
    rows_bku = 0

    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE TABLE ref_skpd")
        cursor.execute("TRUNCATE TABLE bendahara")
        cursor.executemany(
            "INSERT INTO ref_skpd (kode_skpd, nama_skpd) VALUES (%s, %s)",
            [(kode, nama) for kode, nama, _, _ in targets.SKPDS],
        )

        for index, (kode, nama, _, _) in enumerate(targets.SKPDS, start=1):
            cursor.execute(
                "INSERT INTO bendahara (kode_skpd, nama, nik, no_rekening) VALUES (%s, %s, %s, %s)",
                (kode, f"Bendahara {nama.split()[1]}", _nik(rng, index), f"013000{rng.randint(10**6, 10**7 - 1)}"),
            )

        # BKU rows: each SKPD's PENGELUARAN totals exactly the planned realization.
        for kode, nama, pagu, share in targets.SKPDS:
            target = pagu * share
            entry_count = rng.randint(90, 150)
            weights = [rng.uniform(0.4, 1.6) for _ in range(entry_count)]
            scale = target / sum(weights)
            for weight, akun, program in zip(
                weights,
                (targets.AKUN_BELANJA[i % len(targets.AKUN_BELANJA)] for i in range(entry_count)),
                (targets.PROGRAMS[kode][i % len(targets.PROGRAMS[kode])][0] for i in range(entry_count)),
            ):
                day = date(targets.TAHUN_ANGGARAN, 8, 1) + timedelta(days=rng.randint(0, 74))
                day = min(day, date(targets.TAHUN_ANGGARAN, 10, 24))
                cursor.execute(
                    """
                    INSERT INTO bku (kode_skpd, tanggal, kode_akun, uraian, jumlah, jenis, id_bendahara)
                    VALUES (%s, %s, %s, %s, %s, 'PENGELUARAN',
                            (SELECT id_bendahara FROM bendahara WHERE kode_skpd = %s LIMIT 1))
                    """,
                    (
                        kode,
                        day,
                        akun,
                        rng.choice(URAIAN).format(
                            bulan=BULAN.get(day.month, ""), program=targets.PROGRAMS[kode][0][1][:24]
                        )[:160],
                        round(weight * scale, 2),
                        kode,
                    ),
                )
                rows_bku += 1

            # a handful of PENERIMAAN rows, which realization must exclude
            for _ in range(5):
                cursor.execute(
                    """
                    INSERT INTO bku (kode_skpd, tanggal, kode_akun, uraian, jumlah, jenis, id_bendahara)
                    VALUES (%s, %s, '411111', 'Penerimaan retribusi daerah', %s, 'PENERIMAAN',
                            (SELECT id_bendahara FROM bendahara WHERE kode_skpd = %s LIMIT 1))
                    """,
                    (kode, date(targets.TAHUN_ANGGARAN, 10, rng.randint(1, 20)), round(rng.uniform(1e6, 5e8), 2), kode),
                )

    return {"ref_skpd": len(targets.SKPDS), "bendahara": len(targets.SKPDS), "bku": rows_bku}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    connection = connect()
    create_schema(connection)
    summary = seed(connection, seed_value=args.seed)
    connection.close()

    landing.ensure_bucket()
    print(json.dumps(summary, indent=2))
    print(f"SKPD over {targets.ALERT_THRESHOLD:.0%} pagu by design: {targets.over_threshold()}")


if __name__ == "__main__":
    main()
