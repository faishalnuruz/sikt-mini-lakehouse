# Evidence: end-to-end run

Captured on 2026-10-28 against the compose stack. Reproduce with the commands in the README.

## Seeding

```text
$ python -m sikt.seed_simda
{"ref_skpd": 5, "bendahara": 5, "bku": 592}
SKPD over 90% pagu by design: ['1.05.02']

$ python -m sikt.seed_ebudget
{"ref_skpd": 5, "ref_program": 9, "pagu_anggaran": 18, "aset_rows": 400, ...}
```

## CDC captures

```text
$ python -m sikt.cdc_mysql --bootstrap
{"events": 622, "batches_landed": 1, "position": ["mysql-bin.000004", 314038]}

$ python -m sikt.cdc_pg
{"events": 32, "batches_landed": 1, "slot": "sikt_ebudget_cdc"}
```

The 622 binlog events include the 592 BKU rows, 25 PENERIMAAN rows, and the 5 treasurer records.
The slot captured the initial load because it was created before the seed — one ingestion
mechanism, not two.

## A live change, carried by real CDC

```text
$ python -m sikt.simulate --new-bku 1.01.02 50000000000
{"event": "bku_insert", "id_bku": 618, "kode_skpd": "1.01.02", "jumlah": 50000000000.0}

$ python -m sikt.cdc_mysql
{"events": 1, "batches_landed": 1, "position": ["mysql-bin.000004", 314532]}

$ python -m sikt.simulate --revise-pagu 1.02.02 0.75
{"event": "pagu_revision", "kode_skpd": "1.02.02", "factor": 0.75, "rows_updated": 4}

$ python -m sikt.cdc_pg
{"events": 4, "batches_landed": 1, "slot": "sikt_ebudget_cdc"}
```

## dbt

```text
$ dbt run --profiles-dir .    →  PASS=14 WARN=0 ERROR=0 TOTAL=14
$ dbt test --profiles-dir .   →  PASS=42 WARN=0 ERROR=0 TOTAL=42
$ dbt source freshness        →  3 of 3 PASS
```

The 42 tests include the spending invariant (`realisasi ≤ pagu`) and the PII boundary (staging
joined back to raw must expose no raw NIK or account number).

## The alert, before and after the revision

Before the mid-year revision, one SKPD was over the threshold:

```text
$ python -m sikt.alert_realisasi
1 SKPD over 90% pagu
  1.05.02  Dinas Sosial                                   93.0%
```

After the revision travelled through the slot, the loader, and dbt:

```text
2 SKPD over 90% pagu
  1.02.02  Dinas Kesehatan                               94.67%
  1.05.02  Dinas Sosial                                   93.0%
```

The alert payload (Slack Block Kit, with per-SKPD detail) is committed at
`docs/generated/alert_payload.json`.

## Airflow

```text
$ AIRFLOW_HOME=.airflow AIRFLOW__CORE__DAGS_FOLDER=dags \
    .venv-airflow/bin/airflow dags test sikt_apbd_pipeline 2026-10-28

Marking task as SUCCESS: capture_simda_binlog
Marking task as SUCCESS: capture_ebudget_slot
Marking task as SUCCESS: land_reference_extracts
Marking task as SUCCESS: load_landing_zone
Marking task as SUCCESS: dbt_run
Marking task as SUCCESS: dbt_test
Marking task as SUCCESS: check_ingestion_freshness
Marking task as SUCCESS: alert_over_threshold_skpd
Marking task as SUCCESS: sync_metabase
DagRun Finished: ... state=success
```

Inside the DAG run, the alert task printed the two over-threshold SKPDs and the freshness gate
reported all four sources at `0.0h`:

```text
mysql-simda    ok     last run 0.0h
pg-ebudget     ok     last run 0.0h
oracle-aset    ok     last run 0.0h
references     ok     last run 0.0h
```

The DAG's schedule is `0 */2 * * *` — the schedule *is* the SLA: the same two hours the freshness
gate enforces.

## Metabase

Provisioned by API (`python -m sikt.metabase_setup`):

```json
{
  "database_id": 2,
  "questions": ["Realisasi vs pagu per SKPD", "SKPD melewati 90% pagu",
                "Realisasi bulanan (seluruh SKPD)", "Nilai aset per SKPD"],
  "dashboard_id": 2,
  "public_url": "http://127.0.0.1:3300/public/dashboard/36c6c435-0be2-4c0b-80d4-cb847b154015"
}
```

The committed screenshot (`docs/screenshots/metabase-dashboard.png`) shows the rendered public
dashboard, captured through the Chrome DevTools protocol because Metabase renders client-side —
`tools/screenshot_dashboard.py` navigates, waits for the fetches to land, then captures.

## RBAC

```text
$ python -m sikt.grant_bi_access
{"role": "analyst_sikt",
 "schemas_readable": ["analytics_staging", "analytics_intermediate", "analytics_marts"],
 "raw_tables_visible": 0}
```

## Tests

```text
$ .venv/bin/python -m pytest -q
21 passed (13 unit, 8 integration)
$ .venv/bin/ruff check .
All checks passed!
```
