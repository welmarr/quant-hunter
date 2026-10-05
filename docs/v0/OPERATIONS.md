# Native V0 operations and private recovery

The owner runtime defaults to `D:\quant-hunter\.local\v0`. Test instances and
their credentials are separate. Keep `.local`, `.tools`, source data, private
archives and credentials out of Git. Never use the browser-test accounts as
owner credentials. The launcher and account setup are in QUICKSTART.md.

## Stop and back up

Use Ctrl+C in the server terminal and wait for the worker to stop. A runtime
lease rejects a backup while the application is running. From the repository,
with its locked environment installed, create a **new** archive:

```powershell
.venv\Scripts\python.exe -m quant_hunter.web.backup create --runtime D:\quant-hunter\.local\v0 --archive D:\quant-hunter\.local\backups\owner-2026-10-05.qhbackup --code-revision <the-actual-source-commit>
```

Replace the revision placeholder and choose a new dated filename each time.
The command creates the archive's parent directory if necessary and refuses
an existing archive. Source snapshots already retained with experiments remain
inside the runtime; the supplied revision does not replace those exact bytes.

This archive is private, unencrypted storage containing password hashes,
sessions, accounts, experiment evidence, and imported source data under their
original rights. Do not put it in Git or share it as a research export. Protect
it with the owner's existing private storage controls. Master keys and credential
stores are outside this archive; their separate recovery procedure belongs to
the credential component when integrated. A runtime archive is not a backup of
the repository, dependencies, or the entire Windows host.

## Verify restoration in a distinct instance

Restore only to a path that does not exist:

```powershell
.venv\Scripts\python.exe -m quant_hunter.web.backup restore --archive D:\quant-hunter\.local\backups\owner-2026-10-05.qhbackup --destination D:\quant-hunter\.local\v0-restored-owner
pwsh.exe -NoLogo -NoProfile -File scripts\windows\start_v0.ps1 -Runtime D:\quant-hunter\.local\v0-restored-owner -Port 8766
```

Log in with the restored account and inspect datasets, experiment identities,
results and task history. Keep the original instance until the owner decides
otherwise. Both archive creation and restoration refuse overwrites. A failed
restore preserves its incomplete marker and the application refuses to launch
that destination. Choose a different new destination after resolving the error;
no automatic deletion or repair of user files occurs.

The versioned manifest records every file's size and SHA-256. Backup takes the
runtime lease and checks SQLite integrity. Restore bounds ZIP metadata before
loading it, rejects compressed/encrypted/unsafe entries, verifies all bytes
before publication, holds the new runtime lease through extraction, rechecks
each extracted hash and database integrity, then removes the incomplete marker.
Limits are 50,000 runtime files, 64 MiB per file and 30 GB in total. Larger stores
need a separately reviewed streaming backup profile; they are not silently
truncated. Free-space reserves are 20 GiB or 15% of the volume, whichever is
larger. Native `.local` instances and backups share the 30 GB admission budget;
custom external roots require the owner to account for their combined storage.

## Restart semantics and evidence

One process owns each runtime. Queued synthetic jobs resume on startup; running
jobs are reconciled against retained Item 8 evidence and are never blindly
executed again. Imports and source operations interrupted during a crash are
retained as interrupted. Repeating an import or probe is an explicit new
operation, retaining previous immutable records. No startup probe calls an
external service.

An executed restoration copied 265 files with independent byte-for-byte hash
comparison and equal original/restored counts (9 users, 16 jobs, 5 data
operations and 3 owned datasets). The restored application subsequently passed
32 actual Chrome assertions. Exact artifacts and retained test failures are
listed in TEST_REPORT.md. This proves this tested software recovery path, not
host isolation, source licensing, scientific validity or future recovery under
every failure mode.

Private provider configuration is deliberately outside the runtime archive.
Restore of the runtime alone does not restore or activate those credentials.
Use the separate owner procedure in CREDENTIALS.md, preserving all key generations
and the original Windows DPAPI identity context. The new canonical instrument
records live under the runtime research registry and are ordinary immutable
runtime records; credentials and master keys never belong there.
