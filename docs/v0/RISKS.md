# V0 risks

- Existing RISK-017 host isolation is unresolved; synthetic tests never close it.
- Existing RISK-018 registry concurrency evidence requires the governed audit.
- Existing RISK-023 public-repository disclosure and RISK-024 main protection
  remain unresolved; no raw data, credentials or large evidence artifacts enter Git.
- Native app additions require authentication, authorization, hostile-input and
  recovery verification before claiming local delivery.
- Backtest datasets remain synthetic. Bounded BLS/ECB acquisitions have actual
  raw-byte evidence but unknown historical publication/revision timing and
  PENDING quality. Uploaded history is a declaration, not verified availability.
  None establishes empirical validity, profitability or real-money readiness.
- CSV/Parquet imports are capped at 2 MB raw, 16 MB decoded and 100,000 rows;
  they do not yet support the mission's ten-year multi-asset research corpus.
  The larger bounded pipeline remains required work in the requirement matrix.
- Runtime backups contain account hashes and source data; they are private,
  unencrypted archives, never shareable exports. Credential keys remain outside
  this format. Incomplete restores stay quarantined and are never auto-deleted.
- C: is below the mission's free-space reserve. New heavy resources stay on D:.
