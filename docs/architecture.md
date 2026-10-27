# Architecture and decisions

## Flow

```text
SIMDA MySQL ──binlog ROW──┐
                          │   CDC captures (resumable position file / consumed slot)
e-budgeting PG ─slot──────┤
                          ▼
                 landing bucket (S3 API, versioned, partitioned, content-addressed)
                          │   loader: manifest makes reprocessing a no-op
                          ▼
                 dwh PostgreSQL — raw schema (change events applied as upsert/delete)
                          │   ingestion heartbeat per source
                          ▼
                 dbt: staging ──► intermediate ──► marts (star schema, 42 tests)
                          │                              │
                          │                              ├─► Metabase (API-provisioned)
                          │                              └─► #finmon-alerts (over 90% pagu)
                          ▼
                 Airflow DAG: capture → land → load → dbt run → dbt test → freshness → alert → BI
```

## Decisions worth defending

**The initial load flows through the same CDC path as the changes.** `seed_ebudget` creates the
replication slot *before* inserting, so the first 32 events are captured by the slot rather than
loaded by a separate batch tool. This is Debezium's snapshot behaviour, and it means there is one
ingestion mechanism, not two.

**Landing is append-only and content-addressed.** Every object key derives from its content (the
Aset and reference extracts) or from a stream position (CDC batches), and the bucket has versioning
enabled — verified by an integration test. The loader manifest then makes reprocessing a no-op, so
the Airflow schedule is safe to retrigger, and a corrupt checkpoint or state file can only
re-deliver data, never lose it.

**The raw layer applies change events, not a changelog.** CDC records are upserted on the natural
key and deletes really delete, so `raw_bku` mirrors SIMDA. The changelog still exists — in the
immutable landing bucket, which is where an auditor wants it.

**Freshness gates on the ingestion heartbeat, not on row timestamps.** dbt's source freshness
measures when a row landed, so a registry table that nobody has edited for a day looks stale while
the pipeline is perfectly healthy. The loader therefore writes a per-source heartbeat on every run,
and the DAG fails when a source misses its 2-hour SLA. The dbt freshness configuration stays — it
is the right tool for freshly-loaded transactional feeds — but the DAG's gate is the heartbeat.

**PII is hashed at the staging boundary, and a test joins back to raw to prove it.** `stg_bendahara`
exposes SHA-256 fingerprints and display masks, never the raw NIK or account number. The singular
dbt test compares staging against the raw values and fails if any raw value survives — the test
would catch a model edit that "just adds one more column".

**The BI role is granted everything it needs and nothing else.** `analyst_sikt` reads the dbt
schemas and has zero access to `raw`, checked with `has_schema_privilege` in a committed test.
Metabase connects with full privileges for provisioning, which is exactly why the raw schema is
not the thing an analyst browses.

**A spending invariant is a data test, not a hope.** `assert_realisasi_within_pagu` fails the
pipeline if any SKPD's realization exceeds its pagu. The scenario deliberately includes a revision
that pushes Dinas Kesehatan to 94.67% — over the alert threshold, still under 100% — so the alert
demonstrates without breaking the invariant.

**Metabase is provisioned by API, so the BI layer is reproducible.** The database connection, the
four questions, the dashboard layout, and the public link are all created by
`metabase_setup.py`. Nothing about the demo depends on clicks, and re-running the script is
idempotent.

## Failure modes

| Situation | What happens |
| --- | --- |
| A source is down | The capture task fails, Airflow retries twice, nothing lands |
| The same file arrives twice | Content-addressed keys make it a no-op |
| A CDC capture runs twice | The binlog position file / consumed slot yields nothing new |
| The loader runs twice | The manifest skips already-processed objects |
| Raw is ahead of the marts | The reconcile test rebuilds dbt first, then compares |
| A model edit leaks a raw NIK | The PII test fails the pipeline |
| An SKPD overspends | `assert_realisasi_within_pagu` fails the pipeline |
| A source misses the 2-hour SLA | The freshness gate fails the DAG run |
| Metabase is down | The sync task fails; the data pipeline itself is unaffected |
| A bad Slack webhook | The alert exits 3; the DAG marks the task failed |
