# Spec: local server

Problem: show the audit log live in a browser, on this computer only.

Rules
- Binds to 127.0.0.1 only. Any other host (0.0.0.0, a LAN address, localhost) raises an error.
- The log is opened read-only. POST, PUT, DELETE and PATCH return 405.
- `GET /api/run/<run_id>`: the rows of one run, as JSON. 503 with "LOG UNREADABLE" if the log cannot be read.
- `GET /events?run=<run_id>`: server-sent events. One event per new row. The event id is the row id. A client that sends `Last-Event-ID: N` gets only rows after N. If the log cannot be read, the stream sends one `error` event: "LOG UNREADABLE".
- `GET /<file>`: only files inside the fixed `web/` folder. Paths that leave it return 404.
- No outbound call. The port is a parameter (0 = free port, used by tests).

Tests (`tests/test_server.py`): bind address, host refusal, 405 on writes with row count unchanged, read-only handle refuses a write, path traversal (plain and encoded), 3 rows in order, resume after id 2, missing log gives the error event, stop within 2 s and port free, outbound guard.
