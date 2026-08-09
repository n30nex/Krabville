# Observability

Krabville emits one-line JSON operational events to standard output. Container
log rotation remains the retention boundary; logs never contain prompts, model
output, vote identities, credentials, database paths, or control parameters.

## Correlation fields

Every event includes `timestamp`, `level`, `service`, and `event`. Relevant
events add bounded identifiers and measurements:

- `season`, `tick`, and `sequence` correlate engine progress.
- `job`, `kind`, `model`, and `resident` correlate inference work.
- `request` and `operation` correlate control-socket actions.
- `status`, `errorClass`, and `elapsedMs` describe outcomes.

Current event names are `engine_started`, `engine_stopped`, `tick_advanced`,
`model_attempt`, `model_job_failed`, and `control_request`. Tick progress is
logged once per persisted heartbeat, not on every simulation tick.

Set `KRABVILLE_LOG_LEVEL` to a standard Python level such as `INFO` or
`WARNING`. The default is `INFO`.

Runtime state is also available through `/healthz`, `/readyz`, `/livez`,
`/metrics`, and `krabville-manage diagnose --json`; see `OPERATIONS.md`.
