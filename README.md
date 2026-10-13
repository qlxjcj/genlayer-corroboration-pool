# Corroboration Pool

**One fund, shared only by claims that two independent sources back.**

A funder puts up a pool and a brief. During a claim window, anyone may file a
claim naming an **anchor** — a literal token that has to appear in the evidence —
and **two sources**. A claim earns a share only when

- the two sources are on **different hosts**,
- the anchor literally appears in **both** of them, and
- consensus agrees the two documents describe **the same contribution**.

After the claim set freezes, the pool is split **equally across the claims that
survived**. Whatever the split cannot divide goes back to the funder.

Deployed on GenLayer Bradbury: **`0x399a1A7465f7287bcA9da61204bA23CbB1C4a032`**
([explorer](https://explorer-bradbury.genlayer.com/address/0x399a1A7465f7287bcA9da61204bA23CbB1C4a032))

---

## Why this exists

Two of the failure modes that get a submission thrown out are about evidence:

| failure | what it looks like | how this contract stops it |
|---|---|---|
| **no cross-checking** | one source decides the outcome | a claim is worthless unless **two** sources carry the anchor |
| **one source in two hats** | the same page cited twice as if it corroborated itself | the two sources must resolve to **different hosts** |
| **one place propping up many claims** | the same two pages backing five claims | **no two claims in a pool may rest on the same host pair** |

All three are refused **in code**, at filing time, before any model is asked
anything.

---

## What the model does, and what it does not

**The model never decides who gets paid.** It answers one narrow question about
two documents it is shown: *are these about the same contribution, and what is
the span they share?*

The code then decides:

```
claim corroborated  ⇔  anchor literally in document A
                    ∧  anchor literally in document B
                    ∧  consensus says same == "true"
                    ∧  the shared span really occurs in one of the documents
                    ∧  the shared span really carries the anchor
```

Every clause is checked against the text the contract itself fetched, so **the
model can only lose credit, never create it**. `same == "unclear"` is not a yes.
A shared span that is not in the documents is discarded. An answer the contract
cannot use credits nothing at all.

Fetching and asking share one equivalence-principle block, so there is a single
consensus point per assessment and the verdict is computed in code inside it —
validators agree on the decision, not on the wording of a leader's answer.

---

## Why the freeze is forced by the mechanism

The host-pair rule cannot be applied to a claim set that can still grow. So
nothing is judged until the claim window has closed: `assess` refuses before
`claim_by`, `file_claim` refuses at or after it. The evidence set is provably
final between the moment it is read and the moment money moves.

This is not a policy bolted onto the design — the anti-collusion check *requires*
it.

---

## Three invariants

### 1. The claim set is final before anything is judged

```
test_assess_before_the_freeze_is_refused
test_rejects_a_claim_after_the_freeze
test_claims_filed_after_the_freeze_cannot_change_the_set
```

### 2. Every write enforces the same preconditions

All five writes load the same records and check the same things. **A refusal
never mutates anything**, asserted byte for byte.

```
test_every_refusal_leaves_the_state_byte_identical
test_the_pool_goes_read_only_once_settled
test_a_claim_assessed_twice_is_refused
```

### 3. No unit of the fund is ever stranded

`allocate` is pure arithmetic over the frozen, already-assessed claim set and
makes no model call at all. With `n` corroborated claims:

```
share      = total // n
remainder  = total - share * n          -> the funder
paid_total = share * n
paid_total + remainder == total
```

If nothing survives corroboration the whole pool goes home.

```
test_three_claims_leave_a_remainder_for_the_funder
test_nothing_corroborated_refunds_the_whole_pool
test_every_unit_is_accounted_for
test_allocate_is_pure_arithmetic
```

---

## Lifecycle

| pool | meaning |
|---|---|
| `OPEN` | claims may be filed or withdrawn |
| `FROZEN` | the claim set is final |
| `SETTLED` | the fund is fully disbursed |
| `REFUNDED` | the funder withdrew before any claim; escrow refunded whole |

| claim | meaning |
|---|---|
| `FILED` | waiting for the freeze |
| `CORROBORATED` | two independent sources carry the anchor and agree — earns a share |
| `REJECTED` | the anchor, the hosts or the agreement failed — earns nothing |
| `WITHDRAWN` | the claimant stood down before the freeze |

---

## API

**Writes**

| method | note |
|---|---|
| `open_pool(brief, claim_window)` | **payable**. The funder escrows the pool |
| `file_claim(pool_id, claim_id, anchor, sources)` | `sources` is exactly two `http(s)` URLs. Ownership: the claim belongs to its caller |
| `withdraw(pool_id, claim_id)` | claimant only, only before the freeze |
| `assess(pool_id, claim_id)` | permissionless, only after the freeze. Fetches both sources and judges one claim |
| `allocate(pool_id)` | **zero model calls**. Splits the fund once every claim is assessed |
| `cancel(pool_id)` | funder only, only while no claim is filed; refunds the pool whole |

**Views** — all return JSON strings, never a bare `list` or `dict`, because a
`float` in a return value breaks calldata encoding on chain while direct mode
stays green.

| method | returns |
|---|---|
| `get_pool(pool_id)` | config, totals, and every claim with its owner and status |
| `get_claim(pool_id, claim_id)` | full claim record including `hosts`, `same`, `shared`, `reason` |
| `get_pool_count()` | for deriving the next id from a count delta |

**Bounds** — 12 claims per pool, anchor ≤ 120 chars, brief ≤ 400 chars.

---

## Testing

47 direct-mode tests in `tests/direct/test_corroboration_pool.py`, in eight
groups (pool creation, claim filing, withdrawal, corroboration, the freeze
boundary, allocation and funds, uniform write preconditions, views).

Direct mode does not track native value, so `conftest.py` installs two
accounting hooks — payable value into the contract, `emit_transfer` out of it —
so every payout assertion is a real balance change rather than a tautology.

There is deliberately **no catch-all model mock**: a call a test did not
anticipate fails rather than silently returning something plausible. When two
claims share one document, their answers are keyed on **both** documents in
prompt order, because model mocks are first-match-wins.

```
python -m pytest tests/direct -q        # 47 passed
```

---

## Live on chain

Two evidence documents are served from **genuinely different hosts** — one from
`raw.githubusercontent.com`, one from an independent gist — which is exactly
what the contract tests for. Three claims were filed, each resting on a
different pair of hosts, all naming the anchor `SHARD-7`:

| claim | host pair |
|---|---|
| c1 | `raw.githubusercontent.com` + `gist.githubusercontent.com` |
| c2 | `cdn.jsdelivr.net` + `gist.githubusercontent.com` |
| c3 | `cdn.jsdelivr.net` + `raw.githubusercontent.com` |

`open_pool` with 1 GEN, three `file_claim` calls, the freeze, three `assess`
calls and one `allocate`:

```
status              SETTLED
total               1000000000000000000
corroborated_count  3
share               333333333333333333
remainder           1
paid_total          999999999999999999

share * n + remainder     = 1000000000000000000 == total
paid_total + remainder    = 1000000000000000000 == total
remainder == total - share*n
0 <= remainder < n

c1  CORROBORATED | same=true | shared="SHARD-7 cache"
c2  CORROBORATED | same=true | shared="SHARD-7 cache"
c3  CORROBORATED | same=true | shared="SHARD-7 cache"
```

The indivisible remainder — **one atto** — went to the funder, which is the
whole reason the arithmetic is written the way it is. Every claim's shared span
was copied character for character out of the two documents the contract
fetched; compare it against `fixtures/` and the gist and see that a model could
not have invented it.

Check it yourself with `genlayer call <address> get_pool '"p0"'`. Note that
`10^18 // 3` is not exactly representable as a JavaScript `Number`, so read the
raw JSON string and compare with `BigInt`, not with `JSON.parse`.

---

## Source integrity

Deployed and repository source are byte identical:

```
sha256  d37076c2aaa51784b942b4f1f3fea5902b2152a27ec80d06f351ec29b3e9346b
```

Reproduce with `genlayer code <address> --rpc https://rpc-bradbury.genlayer.com`
and compare against `corroboration_pool.py`.
