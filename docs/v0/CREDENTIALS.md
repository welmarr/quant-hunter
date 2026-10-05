# Private credential vault

This server-only component implements the V0 mandate's encrypted configuration,
masking, local revocation and tested master-key rotation. It uses synthetic
credentials in tests. It does not connect to a provider, validate account rights,
place an order, change Windows users/ACLs/security policy, or create scientific
`HOST_ENFORCED` authority. An owner-only API and fixed read-only source clients
remain the integration boundary.

## Location and operating-system protection

Construct `CredentialVault(private_root, application_root)` with explicit absolute
local paths. Production `application_root` is the entire code checkout. Keep the
private root outside that checkout, every runtime, export directory and ordinary
backup/sync root. Both ancestor directions and existing symlink/reparse components
are rejected. The caller must identify other export/sync roots; this class cannot
discover host backup agents or arbitrary external paths.

The complete vault is outside application SQLite: `vault.sqlite3` contains only
slot metadata and authenticated ciphertext. `keys/<random-key-id>.key` files hold
separate master-key generations. Ordinary application backups deliberately exclude
both. No vault key is supplied through environment variables, a URL, logs, or Git.

On Windows, key files are protected with DPAPI **CurrentUser** and
`CRYPTPROTECT_UI_FORBIDDEN`, without `LOCAL_MACHINE`. DPAPI normally requires the
same Windows logon profile and computer; roaming-profile exceptions exist. This
does not verify/change ACLs, isolate another process running as the same user,
resist an administrator, or establish an anti-rollback authority. Native output
buffers are cleared before `LocalFree`; Python/library copies cannot be reliably
zeroized. Do not enable exception-local capture or memory dumps around secret
consumers. [Microsoft protection contract](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata),
[unprotection contract](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptunprotectdata).

On Linux, master keys are protected by owner-only filesystem access, rather than
DPAPI wrapping: new private directories use `0700`, files use `0600`, and existing
wrong modes or owners fail. Files must have one hard link. The implementation does
not repair permissions or alter a host security policy. Other operating systems
fail closed. The POSIX key files contain master-key material; they need the same
separate owner-controlled recovery protection as Windows key files.

## Encryption and identity

The dependency is pinned to **cryptography 50.0.2**. Its high-level Fernet API
authenticates a bounded encrypted envelope containing vault ID, provider, account
alias, slot, `PAPER_OR_READ_ONLY` purpose, credential revision, key ID and secret.
Substituting a token from another slot or revision fails these authenticated
identity checks. Fernet tokens expose their creation timestamp; no secret suffix
or secret length is returned in a management response.
[Official Fernet documentation](https://cryptography.io/en/50.0.2/fernet/).

Official distribution identity, verified from
[PyPI release metadata](https://pypi.org/pypi/cryptography/50.0.2/json):

- `cryptography-50.0.2-cp311-abi3-win_amd64.whl` SHA-256:
  `7afa5a6602a9f29af1f3a2965f831bae7c9d5d597b7cbb716d41ab3b7d89879c`.
- Source distribution SHA-256:
  `7b46165bb56eb4704e2eaaf86f3c940d19154535d9b0ca7d6d590b04060e00d5`.
- The isolated Windows resolver selected `cffi 2.1.1` and `pycparser 3.0`.
  The integration lockfile must record all resolved distributions and hashes.

## Internal API

`set_secret(provider, account, slot, secret: bytes, purpose="PAPER_OR_READ_ONLY")`
creates a new encrypted revision. Labels are bounded nonsecret aliases, not
account numbers, URLs, contact identities or credentials. Obvious live/production
slot identities and any other purpose are refused. This declaration does not prove
the provider-issued key's permissions; concrete clients must enforce their own
read-only or paper host/account contracts. SEC contact/user-agent configuration is
separate from broker credentials and does not become a broker secret by default.

`list_masked()` and `revoke(provider, account, slot)` return only provider, account,
slot, purpose, revision, `CONFIGURED`/`REVOKED`, fixed `********` mask or null,
updated time, and `externally_validated: false`. They never return ciphertext or
key material. Revocation blocks future local use; it makes no external request and
does not revoke an upstream provider key or erase encrypted history.

`with_secret(..., consumer)` supplies bytes only to a trusted synchronous server
consumer. `with_secrets(provider, account, slots, consumer)` supplies a bounded
batch for credentials such as Alpaca's key pair. Their typed consumer result is
internal, not a public-vault response. Consumers must not echo/retain plaintext in
results, exceptions, URLs, logs, telemetry or screenshots. An untrusted plugin,
document, request or caller cannot choose a consumer. Consumer exceptions are
replaced by a fixed error without retaining the original exception chain.
Async consumers are rejected; nested vault operations are unsupported.

Secret use holds SQLite's `BEGIN IMMEDIATE` transaction through the synchronous
consumer, so a competing revoke/rotation cannot return while that admitted use is
still active. Clients must bound their work/timeouts. No automatic external call is
made by any vault operation.

## Rotation, interruption and bounded history

Every mutation uses an atomic SQLite transaction with `synchronous=FULL` and a
rollback journal. `rotate_master()` exclusive-creates and flushes a fresh key
first, then re-encrypts **all** retained credential revisions and updates the active
key reference in one transaction. A process interruption before commit restores
the previous complete database generation. A newly published but uncommitted key
is retained as an orphan. A completed rotation keeps all prior key files.

The software does not silently delete old keys, ciphertext revisions, events or
interrupted files. Admission limits are 8 KiB per secret, 10,000 retained secret
versions, 256 retained key files including orphans, and 50,000 events. At a limit,
the operation fails instead of purging history. These are local software limits,
not protection against an administrator filling or replacing the filesystem.
Unknown schema versions, missing metadata for retained credentials, and missing,
foreign or corrupt active keys fail without generating replacement authority.

Executed tests use actual Windows DPAPI, independent writer processes and a child
terminated with `os._exit` midway through rotation. These prove process-crash
recovery under the tested filesystem; they do not certify power-loss durability,
disk firmware behavior or malicious host resistance.

## Separate owner recovery

1. Stop consumers and the application. If a process was interrupted, reopen the
   vault under its original authorized OS identity to let SQLite recover, then
   close it again. Missing keys must be recovered, not regenerated.
2. Copy the complete private root, including every retained key generation and
   `vault.sqlite3`, into a separate owner-controlled private recovery location.
   Do not place that copy in an application export, source repository or shared
   archive. This component does not automate or transmit a recovery backup.
3. Restore into a new private root with the appropriate owner permissions and all
   key generations present. Windows recovery also requires the original usable
   DPAPI profile/identity context; copying these files alone to another user or
   computer is not a migration procedure.
4. Verify with synthetic credentials before enabling any authorized consumer.
   Restoring an older database can restore an older revocation state. This local
   vault does not prevent rollback; reconcile provider revocation and owner intent
   before using a recovered real credential. No external account or credential
   has been activated by this implementation.
