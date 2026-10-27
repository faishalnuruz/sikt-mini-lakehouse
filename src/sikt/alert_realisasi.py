"""#finmon-alerts: notify the right people when an SKPD crosses its pagu.

The whole pipeline exists for this moment: a treasurer entered a payment, CDC
carried it, dbt rebuilt the marts, and now the Kepala BPKD knows — before the
month closes — which SKPD is running out of budget.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from decimal import Decimal
from pathlib import Path

from sikt.config import SETTINGS
from sikt.loader import connect_dwh

THRESHOLD_LABEL = "90%"
OUTPUT = Path("docs/generated/alert_payload.json")


def over_threshold_rows() -> list[dict]:
    connection = connect_dwh()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT kode_skpd, nama_skpd, pagu_total, realisasi_total,
                   sisa_pagu, persen_realisasi
            FROM analytics_marts.mart_realisasi_skpd
            WHERE over_threshold
            ORDER BY persen_realisasi DESC
            """
        )
        columns = [description[0] for description in cursor.description]
        # PG NUMERIC arrives as Decimal; JSON needs floats.
        rows = [
            {key: (float(value) if isinstance(value, Decimal) else value) for key, value in zip(columns, row)}
            for row in cursor.fetchall()
        ]
    connection.close()
    return rows


def _rupiah(value) -> str:
    amount = float(value)
    return f"Rp {amount / 1e9:,.2f} M" if amount >= 1e9 else f"Rp {amount / 1e6:,.1f} juta"


def build_payload(rows: list[dict]) -> dict:
    """Slack Block Kit message, one block per SKPD over the threshold."""
    blocks: list[dict] = [
        {"type": "header", "text": {
            "type": "plain_text",
            "text": f"🚨 APBD realization over {THRESHOLD_LABEL} pagu",
        }},
        {"type": "section", "text": {
            "type": "mrkdwn",
            "text": f"*{len(rows)} SKPD* melewati {THRESHOLD_LABEL} pagu. Data per hari ini, dari mart "
                    f"`mart_realisasi_skpd` — bukan hasil rekonsiliasi manual.",
        }},
    ]
    for row in rows:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{row['nama_skpd']}* (`{row['kode_skpd']}`)\n"
                    f"• Realisasi: {_rupiah(row['realisasi_total'])} dari pagu {_rupiah(row['pagu_total'])}\n"
                    f"• Persen: *{row['persen_realisasi']}%*  ·  Sisa: {_rupiah(row['sisa_pagu'])}"
                ),
            },
        })
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": "sumber: SIMDA BKU via CDC + e-budgeting pagu · pipeline sikt-mini-lakehouse",
        }],
    })
    return {"text": f"APBD realization over {THRESHOLD_LABEL} pagu", "blocks": blocks}


def send(payload: dict) -> int:
    request = urllib.request.Request(
        SETTINGS.slack_webhook_url or "",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true", help="post to SLACK_WEBHOOK_URL instead of printing")
    args = parser.parse_args()

    rows = over_threshold_rows()
    payload = build_payload(rows)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"skpd_count": len(rows), "skpd": rows, "payload": payload}, indent=2) + "\n")

    print(f"{len(rows)} SKPD over {THRESHOLD_LABEL} pagu")
    for row in rows:
        print(f"  {row['kode_skpd']}  {row['nama_skpd']:44} {row['persen_realisasi']:6}%")

    if args.send:
        if not SETTINGS.slack_webhook_url:
            print("--send needs SLACK_WEBHOOK_URL in the environment", flush=True)
            return 2
        status = send(payload)
        print(f"slack responded {status}")
        return 0 if 200 <= status < 300 else 3

    print(f"\npayload written to {OUTPUT} (dry run; pass --send to post it)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
