# The honest PRD mapping

This repository exists because a PRD-style artifact mapped a BPKD Jakarta job description to three
projects and marked every row "Done" — before anything was built. This document is the corrected
version: what is *actually demonstrated here*, what is *designed only*, and what the production
deployment would add. A reviewer should hold the artifact to this table.

## Job description → what exists here

| JD requirement | Status | Where it is proven |
| --- | --- | --- |
| MySQL | **Real** | SIMDA on MySQL 8.4; ROW binlog with `binlog_row_metadata=FULL`, streamed by the replication protocol — `src/sikt/cdc_mysql.py` |
| PostgreSQL | **Real** | e-budgeting on PostgreSQL 16; logical replication slot with `test_decoding` — `src/sikt/cdc_pg.py` |
| Python | **Real** | The whole package, plus a test suite — `src/sikt/`, `tests/` |
| ETL / Data pipeline | **Real** | CDC → landing → loader → dbt, idempotent at every step — `src/sikt/loader.py` |
| Data warehouse / star schema | **Real, local** | PostgreSQL star schema: 3 dims, 2 facts, 2 marts — `dbt/models/marts/` |
| Data lake | **Real semantics** | S3-compatible, versioned, partitioned landing via the boto3 client — `src/sikt/landing.py`, integration test asserts versioning |
| Airflow | **Real** | 9-task DAG, 2-hour schedule matching the SLA, `dags test` run green — `dags/sikt_apbd_pipeline.py` |
| dbt (tests, staging, marts) | **Real** | 14 models, 42 tests, docs generated — `dbt/` |
| PII handling | **Real** | SHA-256 + display masks at the staging boundary, a test that joins staging back to raw, and an RBAC role with zero raw access — `dbt/models/staging/stg_bendahara.sql`, `src/sikt/grant_bi_access.py` |
| Dashboard | **Real** | Metabase provisioned by API, public dashboard, committed screenshot — `src/sikt/metabase_setup.py` |
| Alerting | **Real, local** | Slack Block Kit payload for every SKPD over 90% pagu; posts when `SLACK_WEBHOOK_URL` is set — `src/sikt/alert_realisasi.py` |
| Oracle | **Designed** | The legacy Aset system arrives as a nightly CSV export — an honest integration pattern for a legacy system, but there is no local Oracle and no LogMiner |
| Debezium + Kafka | **Designed** | Replaced by direct binlog and slot streaming — the same events, without the transport. The swap is two capture modules |
| MWAA | **Designed** | Plain Airflow here; the DAG is the deployable unit |
| BigQuery / Redshift | **Designed** | PostgreSQL locally; the dbt project ports by changing the adapter |
| Dataflow / Pub/Sub (streaming, <30s) | **Not built** | Belongs to project 2 of the PRD — the streaming semantics live in [streaming-ai-features](https://github.com/faishalnuruz/streaming-ai-features); nothing here claims it |
| OpenMetadata | **Not built** | Covered conceptually by the separate [lakehouse-governance](https://github.com/faishalnuruz/lakehouse-governance) project (catalog policies, masking, lineage verification) |

## The three PRD projects, restated honestly

- **P1 — SIKT mini lakehouse**: built here, locally and real. The production-grade pieces
  (Kafka transport, MWAA, BigQuery, Amazon S3 itself) are documented targets, and every one of
  them is a deployment change rather than a redesign.
- **P2 — APBD real-time streaming (<30s, Dataflow, Pub/Sub)**: not built. It is a different
  project with different latency semantics; the alert in this repository is batch-windowed by
  design (the DAG's 2-hour schedule).
- **P3 — Governance and observability**: partially covered here (PII boundary, RBAC, tested
  invariants) and substantially covered by `lakehouse-governance`. OpenMetadata itself is not
  deployed anywhere.

## What to say in the application

"This is a local replication of the SIKT architecture: real MySQL binlog and PostgreSQL
replication-slot CDC, an S3-semantics landing zone, a dbt-built star schema with 42 tests, an
Airflow DAG whose schedule matches the freshness SLA, API-provisioned Metabase, and PII masking
enforced at the staging boundary. Debezium, Kafka, MWAA, and BigQuery are the production
deployment targets, and I have said so explicitly rather than claiming them."

That sentence survives an interview. "100% match, all done" does not.
