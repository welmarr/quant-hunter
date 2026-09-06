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
Verification also requires schema-valid dataset, lineage, artifact, and raw-capture
records to agree on every provenance claim they share; fields present in only one
governed representation remain bound through that representation's canonical
digest rather than being duplicated into another schema. Batch 4B.2 adds a
closed PIT-selection configuration schema. It binds the input dataset, exact UTC
as-of instant including epoch nanoseconds, availability mode, generic observation
key, vintage identity, all four temporal columns, revision statuses, eligibility
and vintage-selection rules, fail-closed ambiguity policy, and deterministic
output ordering. Selection audit evidence is canonical and digest-bound; it does
not create a second dataset-record vocabulary.
