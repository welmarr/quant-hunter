# Versioned Schemas

`schemas/v1/` contains the authoritative JSON Schema Draft 2020-12 foundation
for Stage 1 research objects. Every instance schema has an immutable `$id` and
requires `schema_version: "1.0.0"`; a version change requires a new directory,
new `$id`, migration decision, and retained prior schema.

`common.schema.json` defines shared timestamp, digest, normalized-decimal, and
typed UUIDv7 formats. Registry-shaped schemas include revision metadata for
future append-only records, but this batch implements no allocation, persistence,
canonicalization, hashing, or registry behavior.
