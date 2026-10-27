"""Provision Metabase through its REST API: connection, questions, dashboard.

The BI layer is configured the way infrastructure should be — reproducibly.
Nothing is clicked by hand: the database connection, the questions over the
dbt marts, the dashboard layout, and the public link are all created through
the API, so a reviewer can rebuild the whole consumption layer in one command.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request

METABASE = "http://127.0.0.1:3300"
ADMIN_EMAIL = "admin@sikt.local"
ADMIN_PASSWORD = "sikt-admin-2026"
SITE_NAME = "SIKT Mini Lakehouse"

QUESTIONS = [
    {
        "name": "Realisasi vs pagu per SKPD",
        "description": "Budget ceiling vs realization by SKPD, from mart_realisasi_skpd.",
        "display": "bar",
        "query": """
            SELECT nama_skpd, pagu_total, realisasi_total, persen_realisasi
            FROM analytics_marts.mart_realisasi_skpd
            ORDER BY persen_realisasi DESC
        """,
        "settings": {"graph.dimensions": ["nama_skpd"], "graph.metrics": ["realisasi_total", "pagu_total"]},
    },
    {
        "name": "SKPD melewati 90% pagu",
        "description": "The alert view: SKPDs whose realization crossed 90% of their budget.",
        "display": "table",
        "query": """
            SELECT kode_skpd, nama_skpd, realisasi_total, pagu_total, sisa_pagu, persen_realisasi
            FROM analytics_marts.mart_realisasi_skpd
            WHERE over_threshold
            ORDER BY persen_realisasi DESC
        """,
        "settings": {},
    },
    {
        "name": "Realisasi bulanan (seluruh SKPD)",
        "description": "Monthly spending from the BKU ledger via fact_realisasi.",
        "display": "line",
        "query": """
            SELECT bulan, sum(realisasi) AS realisasi
            FROM analytics_marts.fact_realisasi
            GROUP BY 1 ORDER BY 1
        """,
        "settings": {"graph.dimensions": ["bulan"], "graph.metrics": ["realisasi"]},
    },
    {
        "name": "Nilai aset per SKPD",
        "description": "Fixed assets from the legacy Oracle Aset extract.",
        "display": "bar",
        "query": """
            SELECT s.nama_skpd, a.total_nilai_aset
            FROM analytics_marts.mart_aset_per_skpd a
            JOIN analytics_marts.dim_skpd s USING (kode_skpd)
            ORDER BY a.total_nilai_aset DESC
        """,
        "settings": {"graph.dimensions": ["nama_skpd"], "graph.metrics": ["total_nilai_aset"]},
    },
]


def _request(method: str, path: str, payload: dict | None = None, session: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if session:
        headers["X-Metabase-Session"] = session
    request = urllib.request.Request(
        METABASE + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read().decode()
        return json.loads(body) if body else {}


def wait_until_healthy(timeout_seconds: int = 180) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            _request("GET", "/api/health")
            return
        except (urllib.error.URLError, OSError):
            time.sleep(5)
    raise TimeoutError("metabase did not become healthy in time")


def ensure_setup() -> str:
    """Complete first-time setup if needed, then log in and return a session."""
    properties = _request("GET", "/api/session/properties")
    token = properties.get("setup-token")
    if token:
        session = _request(
            "POST",
            "/api/setup",
            {
                "token": token,
                "user": {
                    "first_name": "SIKT",
                    "last_name": "Admin",
                    "email": ADMIN_EMAIL,
                    "password": ADMIN_PASSWORD,
                    "site_name": SITE_NAME,
                },
                "prefs": {"site_name": SITE_NAME, "site_locale": "en"},
            },
        ).get("id")
        if session:
            return session
    return _request("POST", "/api/session", {"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD})["id"]


def add_database(session: str) -> int:
    existing = _request("GET", "/api/database", session=session)
    for item in existing.get("data", []):
        if item["name"] == "SIKT DWH":
            return item["id"]
    created = _request(
        "POST",
        "/api/database",
        {
            "name": "SIKT DWH",
            "engine": "postgres",
            "details": {
                "host": "ebudget-postgres",  # the compose service, inside the docker network
                "port": 5432,
                "dbname": "dwh",
                "user": "postgres",
                "password": "sikt-postgres",
                "ssl": False,
            },
            "is_full_sync": True,
        },
        session=session,
    )
    return created["id"]


def create_question(session: str, database_id: int, question: dict) -> int:
    """Create the question, or reuse it if a previous run already made it."""
    for card in _request("GET", "/api/card", session=session):
        if card["name"] == question["name"]:
            return card["id"]
    return _request(
        "POST",
        "/api/card",
        {
            "name": question["name"],
            "description": question["description"],
            "dataset_query": {
                "database": database_id,
                "type": "native",
                "native": {"query": question["query"]},
            },
            "display": question["display"],
            "visualization_settings": question["settings"],
        },
        session=session,
    )["id"]


def create_dashboard(session: str, card_ids: list[int]) -> dict:
    existing = _request("GET", "/api/dashboard", session=session)
    dashboard = next((item for item in existing if item["name"] == "SIKT — Realisasi APBD"), None)
    if dashboard is None:
        dashboard = _request(
            "POST",
            "/api/dashboard",
            {"name": "SIKT — Realisasi APBD", "description": "Realisasi vs pagu per SKPD, dari dbt marts"},
            session=session,
        )
    # The layout is always re-put, so a changed layout on a later run still
    # reaches an existing dashboard instead of returning it untouched.

    # Metabase 0.65 removed the per-card endpoint; the layout is replaced
    # wholesale. Negative ids let the API assign real dashcard ids on creation.
    layout = [(0, 0, 9, 6), (9, 0, 9, 6), (0, 6, 12, 6), (12, 6, 6, 6)]
    cards = [
        {
            "id": -(index + 1),
            "card_id": card_id,
            "row": row,
            "col": column,
            "size_x": width,
            "size_y": height,
        }
        for index, (card_id, (column, row, width, height)) in enumerate(zip(card_ids, layout))
    ]
    _request("PUT", f"/api/dashboard/{dashboard['id']}/cards", {"cards": cards}, session=session)
    return dashboard


def create_public_link(session: str, dashboard_id: int) -> str:
    try:
        response = _request("POST", f"/api/dashboard/{dashboard_id}/public_link", {}, session=session)
    except urllib.error.HTTPError:
        response = _request("PUT", f"/api/dashboard/{dashboard_id}/public_link", {}, session=session)
    return f"{METABASE}/public/dashboard/{response['uuid']}"


def provision() -> dict:
    wait_until_healthy()
    session = ensure_setup()
    database_id = add_database(session)
    card_ids = [create_question(session, database_id, question) for question in QUESTIONS]
    dashboard = create_dashboard(session, card_ids)
    public_url = create_public_link(session, dashboard["id"])

    return {
        "database_id": database_id,
        "questions": [q["name"] for q in QUESTIONS],
        "dashboard_id": dashboard["id"],
        "public_url": public_url,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    print(json.dumps(provision(), indent=2))


if __name__ == "__main__":
    main()
