"""Fire real events into the sources, so the CDC path has something to catch.

Every command is a real transaction on a real source: a treasurer entering a
BKU payment in SIMDA, or a mid-year APBD revision in e-budgeting. The next CDC
run picks them up from the binary log or the replication slot.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from sikt import targets
from sikt.seed_ebudget import connect as pg_connect
from sikt.seed_simda import connect as mysql_connect


def new_bku(kode_skpd: str, jumlah: float, uraian: str = "") -> dict:
    connection = mysql_connect()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO bku (kode_skpd, tanggal, kode_akun, uraian, jumlah, jenis, id_bendahara)
            VALUES (%s, CURDATE(), '521111', %s, %s, 'PENGELUARAN',
                    (SELECT id_bendahara FROM bendahara WHERE kode_skpd = %s LIMIT 1))
            """,
            (kode_skpd, uraian or "Pembayaran atas SPP baru", jumlah, kode_skpd),
        )
        inserted = cursor.lastrowid
    connection.close()
    return {"event": "bku_insert", "id_bku": inserted, "kode_skpd": kode_skpd, "jumlah": jumlah}


def revise_pagu(kode_skpd: str, factor: float) -> dict:
    """Perubahan APBD: scale one SKPD's pagu, the mid-year revision case."""
    connection = pg_connect("ebudget")
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE pagu_anggaran SET pagu = pagu * %s, updated_at = now() WHERE kode_skpd = %s AND tahun = %s",
            (factor, kode_skpd, targets.TAHUN_ANGGARAN),
        )
        updated = cursor.rowcount
    connection.commit()
    connection.close()
    return {
        "event": "pagu_revision",
        "kode_skpd": kode_skpd,
        "factor": factor,
        "rows_updated": updated,
        "at": datetime.now(UTC).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new-bku", nargs=2, metavar=("KODE_SKPD", "JUMLAH"), help="insert one BKU payment")
    parser.add_argument("--revise-pagu", nargs=2, metavar=("KODE_SKPD", "FACTOR"), help="scale an SKPD's pagu")
    args = parser.parse_args()

    if args.new_bku:
        kode, jumlah = args.new_bku
        print(json.dumps(new_bku(kode, float(jumlah))))
    if args.revise_pagu:
        kode, factor = args.revise_pagu
        print(json.dumps(revise_pagu(kode, float(factor))))


if __name__ == "__main__":
    main()
