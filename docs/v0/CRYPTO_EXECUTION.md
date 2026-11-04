# Offline crypto execution test plugin

V0-196 provides a reusable typed `CryptoExecutionAdapter` protocol and a concrete
`OfflineCryptoPlugin`. The plugin executes against the actual durable PaperEngine
and Decimal accounting implementation. It has no network transport, endpoint,
credential, exchange account or live mode. Real crypto broker access is explicitly
`NOT_IMPLEMENTED`; the capability is a test plugin, not an enabled product market.

The host constructs an instance with a preexisting PaperEngine, account ID and
authenticated owner ID. Every account read and mutation verifies this owner in
the native journal. The account must contain exclusively CRYPTO_SPOT instruments
and SYNTHETIC evidence in LOCAL_PAPER or REPLAY mode. Existing genesis binds its
cash, explicit bounded UTC trading calendar, base/quote pair, Decimal tick/lot,
strategy risk limits, experiment, code/environment/configuration digests and
mode. These references must already be canonical and owner-authorized in any
future product integration. The low-level plugin, like PaperEngine, cannot prove
registry existence by itself and cannot register, approve or promote research.

`submit(Admit, expected_revision=...)` calls native atomic risk admission before
an order exists. The caller supplies the strategy, quantity, decision time,
available bid/ask and commission budget; it cannot supply a boolean risk approval.
MARKET is the only implemented order type. Long cash-funded spot holdings,
fractional lot sizes, partial fills and request/confirm cancellation are supported.
Limit/stop orders, replacement, shorts, leverage, margin and perpetual/futures
funding execution are unsupported. A crypto label does not silently enable these.
There is no claim that synthetic quoted volume represents exchange liquidity.

The API also exposes account/positions/order queries, bounded outcome and fill
pages, explicit synthetic execution events, marks, connector-health fixtures,
kill controls and reconciliation. Synthetic fills must use a strictly later,
causally available quote and the real bid/ask, fee, slippage and reservation
rules. `synthetic_execution` does not claim to receive a broker execution.
Paging is capped at 100 outcomes or fills and the reviewed native journal remains
bounded at 1,000 commands per account. No second ledger or application database
is introduced. Native CAS, immutable command fingerprints and retained protocol
rejections apply to every mutation. Unsupported plugin-level types are refused
before entering that ledger and are not claimed as journalled broker rejections.

An acknowledgement can be lost after the native transaction commits. The plugin
never retries on its own. Querying the durable order/account/events after restart
establishes whether the command was applied; exact explicit command replay returns
the current state without duplicating cash movement or rolling back newer state.
Conflicting command IDs and stale revisions fail. Native precommit fault injection
also demonstrates full rollback. Test-only fault hooks are trusted constructor
arguments, never request or user configuration.

Independent cash oracle: USD10,000 buys0.1BTC at10,000 with fee1, then sells0.1BTC
at10,100 with fee1. Cash is10,000−1,000−1+1,010−1=10,008. Doubling only the two
fees produces10,006. A separate bid9,999/ask10,001 buy with1bp adverse slippage
rounds upward to the .01 tick at10,002.01, giving cash8,998.799 after0.1BTC and
fee1. These are synthetic numerical software oracles, not market performance.

Offline tests cover these oracles, a fractional fill arriving after cancellation
request, retained actual risk refusals, concurrent competing reservations,
duplicate/conflicting/stale/out-of-order events, both commit fault boundaries,
reconciliation drift, persistent kill/reset, exact owner/mode restrictions and
closed command types. The focused first run found only a test enum spelling
mistake (`CANCELLED` versus native accounting's `CANCELED`); the native code was
unchanged. Final exact test and peer-review evidence is supplied with the frozen
integration manifest. No real account, market data or scientific gate is implied.
