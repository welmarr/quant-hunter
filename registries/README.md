# Registries

Authoritative records use the fixed layout
`registries/<kind>/<typed-id>/vNNNNNN.json`. The supported kind directories are
`families`, `models`, `strategies`, `patterns`, `experiments`, `sources`,
`datasets`, `backlog`, and `costs`.

Stage 1B Batches 3A–3B implement typed UUIDv7 allocation, exclusive
first-revision creation, append-only revision files, compare-and-swap writes,
duplicate-ID detection, and exact-file SHA-256 revision chains. Every new
revision is RFC 8785 JCS UTF-8. Existing revision bytes remain immutable and
their chain identity remains the SHA-256 of those exact bytes.

Authoritative callers use `RegistryStore.governed`, which validates against the
existing versioned schemas and fails closed when a kind has no authoritative
schema. `RegistryStore.for_synthetic_tests` is isolated for low-level temporary
fixtures only. No real registry records are created by Batches 3A–3B. Generated
indexes set `authoritative` to `false`, may be deleted and rebuilt, and must
never be treated as registry authority.
