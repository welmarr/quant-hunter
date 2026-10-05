# Recreated SQLite journal correction

The exact publication checkpoint `3c88f81e59f0842a000aa231ea9921889bead8fe`
passed its local full gate, but Ubuntu run37309100531 failed the existing
parallel credential-writer test. It retained2,326passes, one failure, one
platform skip, one existing warning and93.03%coverage in216.26seconds.
This is a correctness failure, not a waived or deferred test.

During a permission check, a competing SQLite DELETE-mode writer can remove
the optional journal. Another writer can recreate the same name before the
subsequent existence check. The earlier implementation treated that recreated
path as the original failed path and re-raised FileNotFoundError.

The correction makes at most four complete permission/type/link checks when
the optional name has reappeared. Only actual absence or a complete successful
check admits the transaction. A persistent failure, unsafe replacement,
directory, hardlink, symlink or incorrect permissions still fails before opening
the database. No permissions are weakened, no journal/data is deleted by this
correction, and no transaction or credential revision is replayed.

All credential tests pass locally:51passed, one actual-POSIX skip on Windows,
warnings as errors,3.02seconds. Two new regressions exercise a recreated valid
journal and a recreated invalid directory. Existing persistent missing-file,
permissions, concurrency, rotation and revoke tests remain. Ruff, formatting and
strict mypy pass. Independent review passed its three focused hostile cases.
Saved correctionb13af539bc02897e54786a5525aa41ddb6fdca5c is verified on origin.
Exact hosted run37310346592 passed Windows(741.76s) and Ubuntu(315.86s):
2,329tests each, one platform skip, one existing warning; Ubuntu93.03%coverage,
218formatted files and161mypy files. The failed earlier run remains part of
the evidence. This document makes no scientific or host-enforcement claim.
