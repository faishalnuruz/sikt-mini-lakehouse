"""Land reference extracts: the small, slow-moving tables.

CDC belongs to transactional tables that change constantly. Reference data —
SKPD names, program names — is a few hundred rows that change rarely, so it is
extracted as a snapshot into the same landing zone, labelled as what it is.
"""

from __future__ import annotations

import argparse
import hashlib
import json

from sikt import landing
from sikt.seed_ebudget import connect as pg_connect
from sikt.seed_simda import connect as mysql_connect


def land_references() -> dict:
    landing.ensure_bucket()

    mysql = mysql_connect()
    with mysql.cursor() as cursor:
        cursor.execute("SELECT kode_skpd, nama_skpd FROM ref_skpd ORDER BY kode_skpd")
        skpd_records = [{"kode_skpd": row[0], "nama_skpd": row[1]} for row in cursor.fetchall()]
    mysql.close()

    postgres = pg_connect("ebudget")
    with postgres.cursor() as cursor:
        cursor.execute("SELECT kode_program, nama_program FROM ref_program ORDER BY kode_program")
        program_records = [
            {"kode_program": row[0], "nama_program": row[1]} for row in cursor.fetchall()
        ]
    postgres.close()

    already = {key.split("/")[-1] for key in landing.list_objects("references")}
    landed = []
    for name, records in (("ref-skpd.jsonl", skpd_records), ("ref-program.jsonl", program_records)):
        # Content-addressed, like every other landing key: unchanged reference
        # data never lands twice, so the manifest can never skip new data.
        digest = hashlib.md5(json.dumps(records, sort_keys=True).encode()).hexdigest()[:16]
        if f"{name[:-6]}-{digest}.jsonl" in already:
            landed.append({"key": "unchanged", "records": len(records)})
            continue
        key = landing.write_batch("references", f"{name[:-6]}-{digest}.jsonl", records)
        landed.append({"key": key, "records": len(records)})

    return {"ref_skpd": len(skpd_records), "ref_program": len(program_records), "landed": landed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    print(json.dumps(land_references(), indent=2))


if __name__ == "__main__":
    main()
