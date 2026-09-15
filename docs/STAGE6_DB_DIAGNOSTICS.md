# Temporary Stage 6 DB diagnostics

Purpose: distinguish time inside init_db/driver calls from gaps between them on
Streamlit Cloud. No SQL, migration, transaction, retry or business rule is changed.

- `DBDIAG` JSON goes to the existing Cloud log, not to a DB table or file.
- `run_id`, `instance`, `thread` correlate full manager runs; `init_no` numbers the
  init_db calls within a run. Standalone init calls receive their own run ID.
- Every init and remote execute/fetch/commit/rollback/close has a UTC timestamp and
  monotonic elapsed time. `op_id` pairs start/end/error; cursor reads link to their
  execute via `query_id`. An error is followed by end-of-scope records, not success.
- Only init_db scope is traced at SQL level. The 2-second registration watcher and
  normal product/approval queries outside init are deliberately not logged.
- SQL text, bind values, result values, hostnames, paths, tokens, Secrets, browser
  session IDs and exception messages are not logged. SQL labels and error
  categories are allowlisted. Sites contain code filenames/functions/line numbers.
- Elapsed time includes the Python/driver operation, not exclusively server work.
  Driver calls may include transport. SQL logs cannot distinguish network latency
  from Turso server execution by themselves. Logging can add overhead between calls.
- Compare legacy_platform_update op.end UTC with commit op.start UTC to measure
  their gap. Compare commit start/end/error to measure time inside commit.
- Overlapping run IDs show concurrent script executions, but do not prove a lock
  conflict. Cloud currently provides no reliable SQL/session timestamps for older
  failures; do not infer those from unrelated warning timestamps.

Removal: revert ONLY the diagnostic changes to app_database.py and the manager's
trace decorators/import, then remove db_diagnostics.py and its diagnostic tests.
Alternatively set db_diagnostics.ENABLED=False in a separately approved deployment.
No Secrets edit, DB migration or data cleanup is required. Do not suppress failures,
retry writes or remove the legacy platform UPDATE as part of this instrumentation.
