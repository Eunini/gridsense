# Architecture and failure semantics

GridSense has three observation routes:

```text
HTTP device → SQLite outbox → authenticated batch endpoint → database
MQTT device → broker → bridge SQLite outbox → same batch endpoint → database
Browser simulator → IndexedDB outbox → same batch endpoint → database
```

The dashboard reads the database through the API. Its charts, outage detector, exports, and forecasts all use persisted telemetry rather than separate fabricated UI values.

## Event identity and transactions

Each observation has an immutable UUID. A batch contains 1–500 observations. The API authenticates every device in the batch before any insertion. Device credentials are SHA-256 hashes compared with constant-time comparison; read operations have a separate operator credential outside demonstration mode.

SQLite and PostgreSQL both use `INSERT … ON CONFLICT DO NOTHING … RETURNING`. If an event already exists, the API compares the complete normalized payload. An exact replay counts as a duplicate. A conflicting replay produces HTTP 409 and rolls back all new entries in that batch. Arrival order does not determine the latest reading: queries sort by observation time and event ID.

## Acknowledgements and recovery

Both outboxes delete only the IDs acknowledged by a successful batch response. Network loss before or after a server commit is safe: the queue retains its entries and the next attempt is an idempotent replay. A mismatched acknowledgement, HTTP error, or invalid payload retains the queue. Operators must inspect and fix permanently rejected payloads; the reference implementation does not silently discard them.

SQLite uses WAL and separate short-lived connections. The bridge acknowledges an MQTT message only after committing it to its SQLite spool. HTTP upload happens independently. A disk failure prevents that acknowledgement. Invalid or oversized MQTT messages are rejected and acknowledged to avoid an infinite poison-message loop; message payloads and credentials are omitted from logs. Hardware clients must use QoS 1 for broker redelivery.

Use one bridge process per configured device, a stable MQTT client ID, persistent broker storage, and a persistent spool volume. Concurrent independent HTTP senders may replay the same outbox entry; the server's identity checks keep the operation idempotent.

## Offline dashboard

The production build generates a content-versioned service worker that caches the application shell, fonts, and JavaScript. It never intercepts API requests. IndexedDB retains queued observations and the last successful **demo** dashboard snapshot. Real operator responses are not written to this snapshot cache. The operator token lasts only for the browser session.

App-shell installation requires one successful online visit. A saved snapshot is marked as cached and preserves its original observation timestamp. Disconnecting the demo uplink pauses telemetry upload, not the monitoring API; use actual browser/network disconnection to exercise cached-shell recovery.

## Outages and coverage

Two observations below 180 V confirm an interruption; two at or above 205 V confirm restoration. These configurable-in-code demonstration thresholds provide hysteresis and are not an electrical compliance standard. Intermediate voltage does not close an active interruption.

A gap longer than 20 minutes breaks observation continuity. A known interruption is closed at the last observed sample with an uncertain-end marker. The missing interval contributes neither available-grid time nor observed coverage. Grid availability is the fraction of observed adjacent intervals whose endpoints both report voltage of at least 180 V.

## Forecasting and alerting

The seasonal baseline uses the median of recent observations within 30 minutes of the same UTC clock time. It falls back to the last 12 observations when seasonal support is sparse. Every forecast filters out observations at or after the target time. A fixed, time-ordered holdout is scored against training-only predictions and a persistence baseline.

Load alerts compare the current sample with up to 12 preceding observations in the last three hours. The threshold is median plus the larger of 800 W or four scaled median absolute deviations. Low battery is a separate threshold alert. No email, SMS, or push notification is sent; alerts appear in the dashboard.

## Deployment scope

The data model supports multiple sites with one primary inverter each. Reads are capped at 12,000 observations within a maximum seven-day window. This is suitable for the reference sampling rate, not an unbounded industrial telemetry lake. Schema creation is automatic for this first schema; versioned database migrations are needed for future incompatible schema changes.

Compose is designed as a local demonstration. Internet exposure requires a configured TLS gateway, authentication, request-size/rate limits, durable database backups, and authenticated MQTT. The project does not claim audited production readiness or measured hardware accuracy.
