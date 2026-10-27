"""SIKT APBD pipeline: capture CDC, load the landing zone, transform, alert.

The schedule is the SLA: every two hours, because the freshness test in dbt
warns after two hours. If a run fails, the retries give the sources time to
recover; if the data is bad, the dbt tests stop the alert from firing on
numbers that cannot be trusted.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.bash import BashOperator

REPO = Path(__file__).resolve().parents[1]
PY = f'"{REPO}/.venv/bin/python"'
DBT = f'"{REPO}/.venv/bin/dbt"'

with DAG(
    dag_id="sikt_apbd_pipeline",
    description="SIKT mini lakehouse: SIMDA + e-budgeting CDC -> landing -> dbt -> alert -> BI",
    schedule="0 */2 * * *",
    start_date=__import__("datetime").datetime(2026, 10, 1),
    catchup=False,
    default_args={
        "owner": "data-platform",
        "retries": 2,
        "retry_delay": timedelta(minutes=1),
    },
    tags=["sikt", "apbd", "cdc"],
) as dag:
    capture_simda = BashOperator(
        task_id="capture_simda_binlog",
        bash_command=f"{PY} -m sikt.cdc_mysql",
        cwd=str(REPO),
    )
    capture_ebudget = BashOperator(
        task_id="capture_ebudget_slot",
        bash_command=f"{PY} -m sikt.cdc_pg",
        cwd=str(REPO),
    )
    land_references = BashOperator(
        task_id="land_reference_extracts",
        bash_command=f"{PY} -m sikt.land_references && {PY} -m sikt.land_aset",
        cwd=str(REPO),
    )
    load_landing = BashOperator(
        task_id="load_landing_zone",
        bash_command=f"{PY} -m sikt.loader",
        cwd=str(REPO),
    )
    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=f"{DBT} run --profiles-dir .",
        cwd=f"{REPO}/dbt",
    )
    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=f"{DBT} test --profiles-dir .",
        cwd=f"{REPO}/dbt",
    )
    check_freshness = BashOperator(
        task_id="check_ingestion_freshness",
        # Heartbeat-based: fails when a source missed its ingestion SLA, which
        # dbt's row-level freshness cannot express for rarely-changing tables.
        bash_command=f"{PY} -m sikt.freshness --max-age-hours 2",
        cwd=str(REPO),
    )
    alert_realisasi = BashOperator(
        task_id="alert_over_threshold_skpd",
        bash_command=f"{PY} -m sikt.alert_realisasi",
        cwd=str(REPO),
    )
    sync_metabase = BashOperator(
        task_id="sync_metabase",
        bash_command=f"{PY} -m sikt.metabase_setup",
        cwd=str(REPO),
    )

    [capture_simda, capture_ebudget, land_references] >> load_landing
    load_landing >> dbt_run >> dbt_test >> check_freshness
    dbt_test >> alert_realisasi >> sync_metabase
