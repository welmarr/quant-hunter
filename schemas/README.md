# Versioned Schemas

`schemas/v1/` contains the authoritative JSON Schema Draft 2020-12 foundation
for Stage 1 research objects. Every instance schema has an immutable `$id` and
requires `schema_version: "1.0.0"`; a version change requires a new directory,
new `$id`, migration decision, and retained prior schema.

`common.schema.json` defines shared timestamp, digest, normalized-decimal, and
typed UUIDv7 formats. Registry-shaped schemas include revision metadata used by
the append-only registry. Governed writes validate these schemas before emitting
RFC 8785 canonical revisions; kinds without an authoritative schema fail closed.

Batch 4A adds the raw-capture metadata schema and strengthens the generic
artifact manifest with explicit source, dataset, reference, and configuration
provenance. Batch 4B.1 adds the closed derived-dataset lineage manifest, including
the logical schema, deterministic Parquet profile, all three derived identities,
declared row/parent ordering, complete parent evidence, production environment,
and quality disposition. The existing dataset schema remains the authoritative
dataset vocabulary and already binds the three root digests for non-raw layers.
Point-in-time eligibility remains Batch 4B.2.
