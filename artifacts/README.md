# Immutable artifacts

Batch 4A stores exact bytes under
`<artifact-root>/objects/sha256/<first-two>/<64-hex-digest>`. The final path is
derived internally from `sha256:<64 lowercase hex>`, and publication uses a
verified same-directory staging file plus exclusive atomic hard-link creation.
Existing valid bytes deduplicate; existing mismatched bytes are corruption and
are never overwritten.

The authoritative abstraction exposes publication, verification, and reads. It
has no mutation, replacement, or deletion API. New artifact and raw-capture
metadata is schema-validated JCS and may itself be stored as an immutable object.
Raw provider payloads remain byte-for-byte separate from metadata. Files whose
names do not match the complete digest-derived layout, including staging files,
are not authoritative objects.

Only synthetic fixtures are used in Batch 4A. Deterministic Parquet, derived-data
three-digest semantics, normalized/curated data, and point-in-time selection are
deferred to Batch 4B.
