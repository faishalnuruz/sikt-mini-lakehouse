"""Land the Oracle Aset extract into the S3 zone.

The legacy Aset system arrives as a nightly file export — the honest way a
mainframe-era Oracle integration actually behaves. This step lands that file
into the same immutable zone the CDC streams write to, so the warehouse only
ever reads from one place.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json

from sikt import landing
from sikt.config import SETTINGS


def land_all() -> dict:
    landing.ensure_bucket()
    landed = []
    already = {key.split("/")[-1] for key in landing.list_objects("oracle-aset")}
    for path in sorted(SETTINGS.aset_dir.glob("*.csv")):
        with path.open() as handle:
            records = list(csv.DictReader(handle))
        # Content-addressed: the same export never lands twice, so a re-run
        # cannot duplicate rows downstream of the manifest.
        digest = hashlib.md5(path.read_bytes()).hexdigest()[:16]
        name = f"{path.stem}-{digest}.jsonl"
        if name in already:
            landed.append({"file": path.name, "records": len(records), "key": "unchanged"})
            continue
        key = landing.write_batch("oracle-aset", name, records)
        landed.append({"file": path.name, "records": len(records), "key": key})
    return {"files": len(landed), "landed": landed}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    summary = land_all()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
