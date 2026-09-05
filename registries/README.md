# Registries

Authoritative records use the fixed layout
`registries/<kind>/<typed-id>/vNNNNNN.json`. The supported kind directories are
`families`, `models`, `strategies`, `patterns`, `experiments`, `sources`,
`datasets`, `backlog`, and `costs`.

Stage 1B Batch 3A implements typed UUIDv7 allocation, exclusive first-revision
creation, append-only revision files, compare-and-swap writes, duplicate-ID
detection, and exact-file SHA-256 revision chains. The revision digest is a
narrow integrity primitive over the stored UTF-8 bytes; it is not the general
JCS canonicalization and hashing system deferred to Batch 3B.

Callers may provide a schema validator to `RegistryStore`; the core always
checks the managed identity and revision envelope. No real registry records are
created by Batch 3A. Generated indexes set `authoritative` to `false`, may be
deleted and rebuilt, and must never be treated as registry authority.
