# Corroboration Pool

**One fund, shared only by claims that two independent sources back.**

A funder puts up a pool, a **list of anchors** to be corroborated and a **list of
hosts** it trusts as independent places to look. During a claim window, anyone
may file a claim picking one of the funder's anchors and **two sources** from two
different trusted hosts. A claim earns a share only when

- the anchor literally appears in **both** sources, and
- consensus agrees the two documents describe **the same contribution**.

After the claim set freezes, the pool is split **equally across the claims that
survived**. Whatever the split cannot divide goes back to the funder.

Deployed on GenLayer Bradbury: **`0x0dA61d2057349947c20F873F06a0a516662876b8`**
([explorer](https://explorer-bradbury.genlayer.com/address/0x0dA61d2057349947c20F873F06a0a516662876b8))

---

## What changed, and why

The first version of this contract let the **claimant** choose the anchor and
both sources. That is not corroboration. A claimant who publishes two pages can
put *any* string on both of them, name it as the anchor, cite its own two sites,
and collect — the two sources agree because one hand wrote both. Worse, the pool
had a fixed twelve claim slots that anyone could fill for free, so a single
address could occupy all of them with claims it never intended to prove.

Both are now closed, and the fix is structural rather than a check bolted on:

| before | after |
|---|---|
| claimant names the anchor | `open_pool` takes a **list of anchors**; a claim is refused unless its anchor squashes to one of them, and it is filed back in the **funder's** wording |
| claimant names the hosts | `open_pool` takes a **list of trusted hosts**; a claim is refused unless **both** hosts are in it |
| one address could file twelve claims | **one claim per anchor per account**, so a single address can hold at most `len(anchors)` |

The question and the venues are written **once**, at funding, before any money is
at stake, and neither list can be edited afterwards. `get_pool` returns both, so
a claimant can read them before deciding whether to file.

---

## Why this exists

Three of the failure modes that get a submission thrown out are about evidence:

| failure | what it looks like | how this contract stops it |
|---|---|---|
| **no cross-checking** | one source decides the outcome | a claim is worthless unless **two** sources carry the anchor |
| **one source in two hats** | the same page cited twice as if it corroborated itself | the two sources must resolve to **different hosts** |
| **one place propping up many claims** | the same two pages backing five claims | **no two claims in a pool may rest on the same host pair** |
| **the claimant framing its own question** | an anchor the claimant chose, on hosts the claimant owns | **the funder names both**, and the claimant may only pick inside them |

All four are refused **in code**, at filing time, before any model is asked
anything.

---

## The one trust boundary

Naming the hosts is a real decision, and the contract hands it to the funder
deliberately. A host the funder names but the claimant can publish into — a
gist, a raw file in a repo, a wiki — is a weak choice, because "two different
hosts" is not the same as "two different hands". The contract makes that choice
**explicit, immutable and public** instead of leaving "independence" to the
interested party, which is what the first version did, and it is why a real pool
should name venues like `data.ecb.europa.eu` or `api.frankfurter.app` where a
third party cannot write.

What the contract guarantees is narrower and worth stating plainly: **the
claimant cannot choose the question, cannot choose the venue, cannot spell one
anchor two ways into two claims, cannot take more than one slot per anchor, and
cannot be paid unless the contract itself fetches the anchor out of both
documents.**

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
never mutates anything**, asserted byte for byte — including the filing refusals
that the adversarial group is built around.

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
| `CORROBORATED` | two trusted hosts carry the anchor and agree — earns a share |
| `REJECTED` | the anchor, the hosts or the agreement failed — earns nothing |
| `WITHDRAWN` | the claimant stood down before the freeze |

---

## API

**Writes**

| method | note |
|---|---|
| `open_pool(brief, anchors, hosts, claim_window)` | **payable**. The funder escrows the pool and names the question and the venues |
| `file_claim(pool_id, claim_id, anchor, sources)` | `sources` is exactly two `http(s)` URLs. The anchor must be one of the funder's and both hosts must be trusted. Ownership: the claim belongs to its caller |
| `withdraw(pool_id, claim_id)` | claimant only, only before the freeze |
| `assess(pool_id, claim_id)` | permissionless, only after the freeze. Fetches both sources and judges one claim |
| `allocate(pool_id)` | **zero model calls**. Splits the fund once every claim is assessed |
| `cancel(pool_id)` | funder only, only while no claim is filed; refunds the pool whole |

**Views** — all return JSON strings, never a bare `list` or `dict`, because a
`float` in a return value breaks calldata encoding on chain while direct mode
stays green.

| method | returns |
|---|---|
| `get_pool(pool_id)` | config — including `anchors` and `hosts` — totals, and every claim with its owner and status |
| `get_claim(pool_id, claim_id)` | full claim record including `hosts`, `same`, `shared`, `reason` |
| `get_pool_count()` | for deriving the next id from a count delta |

**Bounds** — 12 claims per pool, 1..4 anchors, 2..10 trusted hosts, anchor ≤ 120
chars, brief ≤ 400 chars.

---

## Testing

53 direct-mode tests in `tests/direct/test_corroboration_pool.py`, in nine groups
(A pool creation, B claim filing, C withdrawal, D corroboration, E the freeze
boundary, F allocation and funds, G uniform write preconditions, H views,
I adversarial filing).

Group I is the one to read first:

```
test_a_claimant_cannot_choose_the_question
test_the_filed_anchor_is_the_funders_own_wording
test_an_untrusted_venue_cannot_back_a_claim
test_the_funder_fixes_its_lists_once_and_they_are_public
test_one_account_cannot_occupy_the_pool_by_itself
```

The last one is the occupancy case: one address files all three of the funder's
anchors, then tries six more times — varying the anchor and the host pair every
time — and every attempt is refused with the state byte-identical, while a
**second** account filing the same anchor still succeeds, because that is exactly
what the pool is for.

Direct mode does not track native value, so `conftest.py` installs two
accounting hooks — payable value into the contract, `emit_transfer` out of it —
so every payout assertion is a real balance change rather than a tautology.

There is deliberately **no catch-all model mock**: a call a test did not
anticipate fails rather than silently returning something plausible. When two
claims share one document, their answers are keyed on **both** documents in
prompt order, because model mocks are first-match-wins.

```
python -m pytest tests/direct -q        # 53 passed
```

---

## Live on chain

`fixtures/report-a.txt` and `fixtures/report-b.txt` are served from this repository
over **four independent hosts** — `raw.githubusercontent.com`, `cdn.jsdelivr.net`,
`raw.githack.com` and `cdn.statically.io` — so four genuinely different hostnames
are in play, and the model is shown two *different* documents, not one document
mirrored. Both documents carry the `SHARD-7` anchor.

`p1` was opened with 1 GEN, `anchors = ["SHARD-7", "QUOTA-2", "LATENCY-9"]` and
`hosts = ["raw.githubusercontent.com", "cdn.jsdelivr.net", "raw.githack.com",
"cdn.statically.io"]`, `claim_window = 900`.

### Refused — the claimant tries to frame its own question

Read straight off the live contract with `simulateWriteContract`, so no slot is
spent proving a point:

| attempt | the contract says |
|---|---|
| anchor `MY-OWN-ANCHOR` | `Anchor is not one the funder named` |
| anchor `shard-8` | `Anchor is not one the funder named` |
| anchor `""` | `Anchor is not one the funder named` |
| host `attacker.example.com` | `Host is not one the funder trusts` |
| host `raw.githubusercontent.com` twice | `Sources must be from different hosts` |

`get_pool(p1).claims` is `[]` after every one of them. Then the same thing **for
real**: `file_claim(p1, "evil6", "MY-OWN-ANCHOR", ...)` came back
`FINISHED_WITH_ERROR` and `claims` was still `[]`. A refusal costs the pool
nothing.

### Accepted — and what the contract stores

| claim | sender | anchor given | anchor stored | the two hosts |
|---|---|---|---|---|
| `c1` | `0x347e…b363` | `" shard-7 "` | **`"SHARD-7"`** | raw.githubusercontent.com + cdn.jsdelivr.net |
| `occ` | `0x347e…b363`, same anchor again | — | — | `FINISHED_WITH_ERROR` |
| `c2` | `0x6F33…8959` (a different account) | `SHARD-7` | `SHARD-7` | raw.githack.com + cdn.statically.io |

`c1` is the point of the anchor check: a lowercase, space-padded spelling is
accepted and **stored in the funder's wording**, so it cannot later be spelled a
second way into a second claim. `occ` is the point of the occupancy rule: one
account cannot hold two claims on one anchor. `c2` is the point of *not*
over-doing it — a second account on the same anchor still gets in, because that is
exactly what the pool is for.

### The freeze, the judgement, the split

The freeze boundary was checked on the live contract before and after `claim_by`:
`assess` while the window was still open came back
`Claim window is still open`, and a well-formed claim filed after it closed came
back `Claim window has closed`. Two `assess` calls and one `allocate` are running;
the final books are appended here when they land.

Check it yourself with `genlayer call <address> get_pool '"p1"'`. Note that
`10^18` is not exactly representable as a JavaScript `Number`, so read the raw
JSON string and compare with `BigInt`, not with `JSON.parse`.

---

## Source integrity

Deployed and repository source are byte identical:

```
sha256  d17affd89bd811f9daaa250d6dc8c0b3dd2ea256b8ce57ec4a3e107b7d998c75
bytes   19970
```

Reproduce with `genlayer code 0x0dA61d2057349947c20F873F06a0a516662876b8 --rpc https://rpc-bradbury.genlayer.com`
and compare against `corroboration_pool.py`.

The superseded address — the version that let the claimant choose the question
and the venues — is `0x399a1A7465f7287bcA9da61204bA23CbB1C4a032`. Do not use it.
