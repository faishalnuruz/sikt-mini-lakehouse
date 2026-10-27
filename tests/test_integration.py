"""Integration tests: re-verify the live flow against the compose stack.

Run with the stack up:

    docker compose up -d
    python -m sikt.seed_simda && python -m sikt.seed_ebudget
    .venv/bin/python -m pytest -m integration

These tests deliberately re-run parts of the pipeline, because a pipeline that
cannot be re-run is the failure mode the whole design guards against.
"""

import pytest

from sikt import landing, loader
from sikt.config import SETTINGS
from sikt.loader import connect_dwh

pytestmark = pytest.mark.integration


def test_cdc_mysql_resumes_from_the_saved_position():
    """Drain, then drain again: a second capture with no source change is empty."""
    from sikt.cdc_mysql import stream_once

    stream_once()  # drain whatever the source has pending, from any position
    second = stream_once()

    # No new source events means no new landing batch, at whatever position we
    # were in: this is what makes the scheduled capture safe to retrigger.
    assert second["events"] == 0
    assert second["batches_landed"] == 0


def test_a_new_bku_entry_flows_to_the_raw_layer():
    from sikt import simulate
    from sikt.cdc_mysql import stream_once

    connection = connect_dwh()
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM raw.raw_bku")
        before = cursor.fetchone()[0]
    connection.close()

    inserted = simulate.new_bku("1.04.02", 123_450_000.00)
    capture = stream_once()
    loader.load()

    connection = connect_dwh()
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM raw.raw_bku")
        after = cursor.fetchone()[0]
        cursor.execute(
            "SELECT uraian, jumlah FROM raw.raw_bku WHERE id_bku = %s", (inserted["id_bku"],)
        )
        landed = cursor.fetchone()
    connection.close()

    assert capture["events"] >= 1
    assert after == before + 1
    assert landed is not None
    assert float(landed[1]) == 123_450_000.00


def test_loader_manifest_makes_reprocessing_a_no_op():
    first = loader.load()

    assert first["objects_processed"] == 0
    assert first["records_applied"] == 0


def test_pii_never_crosses_the_staging_boundary():
    connection = connect_dwh()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT s.id_bendahara
            FROM analytics_staging.stg_bendahara s
            JOIN raw.raw_bendahara r USING (id_bendahara)
            WHERE s.nik_masked = r.nik
               OR s.no_rekening_masked = r.no_rekening
            """
        )
        leaks = cursor.fetchall()

        cursor.execute("SELECT count(*) FROM analytics_staging.stg_bendahara WHERE length(nik_hash) <> 64")
        bad_hashes = cursor.fetchone()[0]
    connection.close()

    assert leaks == []
    assert bad_hashes == 0


def test_the_bi_role_cannot_touch_the_raw_schema():
    connection = connect_dwh()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT has_schema_privilege('analyst_sikt', 'raw', 'USAGE') AS raw_usage,
                   has_schema_privilege('analyst_sikt', 'analytics_marts', 'USAGE') AS marts_usage
            """
        )
        raw_usage, marts_usage = cursor.fetchone()
    connection.close()

    assert raw_usage is False
    assert marts_usage is True


def test_mart_reconciles_with_the_raw_ledger():
    """Raw may be ahead of the mart (CDC lands continuously); rebuild, then compare."""
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [str(root / ".venv/bin/dbt"), "run", "--profiles-dir", "."],
        cwd=root / "dbt", check=True, capture_output=True,
    )

    connection = connect_dwh()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT kode_skpd, sum(jumlah)
            FROM raw.raw_bku
            WHERE jenis = 'PENGELUARAN'
            GROUP BY 1
            """
        )
        ledger = dict(cursor.fetchall())

        cursor.execute("SELECT kode_skpd, realisasi_total FROM analytics_marts.mart_realisasi_skpd")
        mart = {row[0]: float(row[1]) for row in cursor.fetchall()}
    connection.close()

    assert set(mart) == set(ledger)
    for kode, total in ledger.items():
        assert abs(mart[kode] - float(total)) < 1.0


def test_the_alert_fires_for_the_seeded_over_threshold_skpd():
    """The scenario guarantees Dinas Sosial lands over 90% from the seed alone."""
    from sikt.alert_realisasi import over_threshold_rows

    rows = over_threshold_rows()

    assert "1.05.02" in [row["kode_skpd"] for row in rows]
    for row in rows:
        assert row["persen_realisasi"] > 90.0
        assert row["realisasi_total"] <= row["pagu_total"]  # the APBD invariant


def test_the_landing_zone_is_versioned():
    s3 = landing.client()
    versioning = s3.get_bucket_versioning(Bucket=SETTINGS.landing_bucket)

    assert versioning.get("Status") == "Enabled"
