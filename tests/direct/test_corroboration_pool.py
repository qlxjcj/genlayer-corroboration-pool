"""Direct-mode tests for Corroboration Pool.

Groups A-H map onto the failure modes this contract exists to kill and the
three lessons it is built around:

  A  pool creation            -- the fund is escrowed whole
  B  claim filing             -- two sources must be genuinely independent
  C  withdrawal               -- a claim belongs to its claimant
  D  corroboration            -- the model only says whether two documents agree;
                                 the code checks the anchors and the span
  E  the freeze boundary      -- the anti-collusion rule needs the final set
  F  allocation and funds     -- every unit reaches exactly one address
  G  uniform write preconditions -- every refusal leaves the state untouched
  H  views                    -- no float or list ever leaves the contract
"""

import json

import pytest

from conftest import (
    ANCHOR,
    ANCHOR_OTHER,
    BAD_ADDR,
    BRIEF,
    CLAIMANT_A,
    CLAIMANT_B,
    CLAIMANT_C,
    FUNDER,
    POOL,
    STRANGER,
    URL_ALPHA,
    URL_ALPHA_2,
    URL_ALPHA_PORT,
    URL_ALPHA_USER,
    URL_BRAVO,
    URL_BRAVO_2,
    URL_CHARLIE,
    URL_DELTA,
    URL_EMPTY,
    URL_ERROR,
    URL_FTP,
    URL_WRAP,
    allocate,
    ans,
    assess,
    balance,
    claim_state,
    contract_balance,
    file_claim,
    full_snapshot,
    open_pool,
    pool_state,
    remock,
    iso,
)


URL_GOLF = "https://golf.example.com/doc"
URL_HOTEL = "https://hotel.example.com/doc"


def pair(*urls):
    return list(urls)


def pair_ans(token_a, token_b, same, shared=""):
    """Key the answer on BOTH documents in prompt order. Two claims whose
    sources share one body would otherwise steal each other's mock, because
    model mocks are first-match-wins. The pattern must cross newlines: DOC A
    and DOC B sit on different lines and '.' does not match '\\n'."""
    return (r"[\s\S]*" + token_a + r"[\s\S]*" + token_b + r"[\s\S]*", ans(same, shared))


# ==========================================================================
# A. pool creation
# ==========================================================================


def test_open_pool_escrows_the_whole_fund(pool):
    vm, c = pool
    before = contract_balance(vm)
    pid = open_pool(vm, c)
    assert contract_balance(vm) == before + POOL
    p = pool_state(vm, c, pid)
    assert p["status"] == "OPEN"
    assert p["total"] == POOL
    assert p["funder"] == FUNDER
    assert p["brief"] == BRIEF
    assert p["claims"] == []


def test_rejects_a_bad_brief(pool):
    vm, c = pool
    for bad in ("", "   ", "x" * 500):
        with pytest.raises(Exception):
            open_pool(vm, c, brief=bad)


def test_rejects_a_non_positive_window(pool):
    vm, c = pool
    for bad in (0, -5):
        with pytest.raises(Exception):
            open_pool(vm, c, window=bad)


def test_rejects_a_zero_pool(pool):
    vm, c = pool
    with pytest.raises(Exception):
        open_pool(vm, c, value=0)


# ==========================================================================
# B. claim filing -- two sources must be genuinely independent
# ==========================================================================


def test_files_a_claim_while_the_window_is_open(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    assert file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 99) == "FILED"
    cl = claim_state(vm, c, pid, "c1")
    assert cl["claimant"] == CLAIMANT_A
    assert cl["hosts"] == ["alpha.example.com", "bravo.example.com"]
    assert cl["status"] == "FILED"


def test_rejects_a_claim_after_the_freeze(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    for t in (100, 500):
        with pytest.raises(Exception):
            file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), t)
    assert pool_state(vm, c, pid)["claims"] == []


def test_rejects_a_bad_claim_id(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    for bad in ("", "   ", "x" * 50):
        with pytest.raises(Exception):
            file_claim(vm, c, pid, bad, ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    assert file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10) == "FILED"
    with pytest.raises(Exception):
        file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_CHARLIE, URL_DELTA), 10)


def test_rejects_a_bad_anchor(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    for bad in ("", "   ", "x" * 200):
        with pytest.raises(Exception):
            file_claim(vm, c, pid, "c1", bad, pair(URL_ALPHA, URL_BRAVO), 10)


def test_rejects_a_bad_source_list(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    cases = [
        pair(URL_ALPHA),
        pair(URL_ALPHA, URL_BRAVO, URL_CHARLIE),
        pair(URL_FTP, URL_BRAVO),
        pair(URL_ALPHA, URL_ALPHA),
        pair("", URL_BRAVO),
    ]
    for bad in cases:
        with pytest.raises(Exception):
            file_claim(vm, c, pid, "c1", ANCHOR, bad, 10)


def test_rejects_two_sources_on_the_same_host(pool):
    """One source wearing two hats is not corroboration. This is failure mode
    number six, and it is refused in code rather than argued about later."""
    vm, c = pool
    pid = open_pool(vm, c)
    for b in (URL_ALPHA_2, URL_ALPHA_PORT, URL_ALPHA_USER):
        with pytest.raises(Exception):
            file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, b), 10)
    assert pool_state(vm, c, pid)["claims"] == []


def test_the_host_ignores_scheme_port_path_and_userinfo(pool):
    vm, c = pool
    for url in (URL_ALPHA, URL_ALPHA_2, URL_ALPHA_PORT, URL_ALPHA_USER):
        pid = open_pool(vm, c, total=1)
        assert file_claim(vm, c, pid, "c1", ANCHOR, pair(url, URL_BRAVO), 10) == "FILED"
        assert claim_state(vm, c, pid, "c1")["hosts"] == [
            "alpha.example.com", "bravo.example.com"]


def test_rejects_a_host_pair_that_already_backs_a_claim(pool):
    """Anti-collusion: one account cannot prop up several claims from the same
    two places, even by citing a different page on the same host."""
    vm, c = pool
    pid = open_pool(vm, c)
    assert file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10) == "FILED"
    for cid, srcs in (
        ("c2", pair(URL_BRAVO, URL_ALPHA)),          # same pair, reversed
        ("c3", pair(URL_ALPHA_2, URL_BRAVO)),        # same hosts, other page
        ("c4", pair(URL_BRAVO_2, URL_ALPHA_2)),      # same hosts again
    ):
        with pytest.raises(Exception):
            file_claim(vm, c, pid, cid, ANCHOR, srcs, 10, sender=CLAIMANT_B)
    # a genuinely different pair is fine
    assert file_claim(vm, c, pid, "c5", ANCHOR,
                      pair(URL_CHARLIE, URL_DELTA), 10, sender=CLAIMANT_B) == "FILED"


def test_a_withdrawn_claim_frees_its_host_pair(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    with pytest.raises(Exception):
        file_claim(vm, c, pid, "c2", ANCHOR, pair(URL_BRAVO, URL_ALPHA), 10,
                   sender=CLAIMANT_B)
    vm.warp(iso(20))
    vm.sender = CLAIMANT_A
    assert c.withdraw(pid, "c1") == "WITHDRAWN"
    assert file_claim(vm, c, pid, "c2", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 30,
                      sender=CLAIMANT_B) == "FILED"


def test_rejects_when_the_pool_is_full(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    hosts = ["h%d.example.com" % i for i in range(30)]
    urls = ["https://" + h + "/doc" for h in hosts]
    for i in range(12):
        vm.mock_web(".*h" + str(i) + "\\.example\\.com.*",
                    {"method": "GET", "status": 200, "body": "h%d doc" % i})
        assert file_claim(vm, c, pid, "c%d" % i, ANCHOR,
                          pair(urls[2 * i], urls[2 * i + 1]), 10) == "FILED"
    with pytest.raises(Exception):
        file_claim(vm, c, pid, "c99", ANCHOR, pair(urls[0], urls[1]), 10)


# ==========================================================================
# C. withdrawal -- a claim belongs to its claimant
# ==========================================================================


def test_only_the_claimant_withdraws(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    for sender in (STRANGER, FUNDER, CLAIMANT_B):
        vm.warp(iso(20))
        vm.sender = sender
        with pytest.raises(Exception):
            c.withdraw(pid, "c1")
    vm.sender = CLAIMANT_A
    assert c.withdraw(pid, "c1") == "WITHDRAWN"


def test_withdraw_only_before_the_freeze(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    vm.warp(iso(150))
    vm.sender = CLAIMANT_A
    with pytest.raises(Exception):
        c.withdraw(pid, "c1")
    assert claim_state(vm, c, pid, "c1")["status"] == "FILED"


def test_a_withdrawn_claim_cannot_move_again(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    vm.warp(iso(20))
    vm.sender = CLAIMANT_A
    c.withdraw(pid, "c1")
    with pytest.raises(Exception):
        c.withdraw(pid, "c1")
    with pytest.raises(Exception):
        assess(vm, c, pid, "c1", 200)
    assert claim_state(vm, c, pid, "c1")["status"] == "WITHDRAWN"


# ==========================================================================
# D. corroboration -- the model says whether they agree, the code checks
# ==========================================================================


def test_two_independent_sources_that_agree(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    remock(vm, llm=[(r".*alpha-report.*", ans("true", "SHARD-7 cache shipped on 2026-01-05"))])
    assert assess(vm, c, pid, "c1", 200) == "CORROBORATED"
    cl = claim_state(vm, c, pid, "c1")
    assert cl["same"] == "true"
    assert cl["reason"] == "two independent sources carry the anchor and agree"


def test_the_anchor_missing_from_one_source_rejects(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_DELTA), 10)
    remock(vm, llm=[(r".*alpha-report.*", ans("true", "SHARD-7 cache"))])
    assert assess(vm, c, pid, "c1", 200) == "REJECTED"
    assert claim_state(vm, c, pid, "c1")["reason"] == "the anchor is not in both sources"


def test_the_anchor_missing_from_both_rejects(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR_OTHER, pair(URL_ALPHA, URL_BRAVO), 10)
    remock(vm, llm=[(r".*alpha-report.*", ans("true", "QUOTA-2 rollout"))])
    assert assess(vm, c, pid, "c1", 200) == "REJECTED"


def test_sources_that_do_not_agree_reject(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_CHARLIE), 10)
    remock(vm, llm=[(r".*alpha-report.*", ans("false", ""))])
    assert assess(vm, c, pid, "c1", 200) == "REJECTED"
    assert claim_state(vm, c, pid, "c1")["reason"] == \
        "the two sources do not describe the same thing"


def test_unclear_agreement_rejects(pool):
    """Unclear is not a yes. Failure is the safe direction."""
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    remock(vm, llm=[(r".*alpha-report.*", ans("unclear", "SHARD-7 cache"))])
    assert assess(vm, c, pid, "c1", 200) == "REJECTED"
    assert claim_state(vm, c, pid, "c1")["same"] == "unclear"


def test_a_fabricated_shared_span_rejects(pool):
    """The model cannot manufacture agreement with invented text."""
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    remock(vm, llm=[(r".*alpha-report.*",
                     ans("true", "the SHARD-7 cache was delivered by a dragon"))])
    assert assess(vm, c, pid, "c1", 200) == "REJECTED"
    assert claim_state(vm, c, pid, "c1")["reason"] == \
        "no shared span naming the anchor"


def test_a_shared_span_that_does_not_name_the_anchor_rejects(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    remock(vm, llm=[(r".*alpha-report.*", ans("true", "Release signed off."))])
    assert assess(vm, c, pid, "c1", 200) == "REJECTED"


def test_an_empty_anchor_never_passes(pool):
    """The empty-string trap: '' is a substring of absolutely everything."""
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", "x", pair(URL_ALPHA, URL_BRAVO), 10)
    remock(vm, llm=[(r".*alpha-report.*", ans("true", ""))])
    assert assess(vm, c, pid, "c1", 200) == "REJECTED"


def test_an_unreadable_source_rejects_the_claim(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_ERROR), 10)
    remock(vm, llm=[(r".*alpha-report.*", ans("true", "SHARD-7 cache shipped"))])
    assert assess(vm, c, pid, "c1", 200) == "REJECTED"
    assert claim_state(vm, c, pid, "c1")["reason"] == "the anchor is not in both sources"


def test_an_anchor_wrapped_across_a_line_is_still_found(pool):
    """A renderer broke the token over two lines. Whitespace-insensitive
    matching still sees it."""
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_WRAP, URL_ALPHA), 10)
    remock(vm, llm=[(r".*foxtrot-mirror.*", ans("true", "SHARD-\n7 cache shipped"))])
    assert assess(vm, c, pid, "c1", 200) == "CORROBORATED"


def test_a_malformed_model_answer_is_fail_closed(pool):
    """A shape the contract cannot use credits nothing and still terminates."""
    for bad in ('{"same": "nope"}', "not json at all", '{"shared": 7}', ""):
        vm, c = pool
        pid = open_pool(vm, c)
        file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
        remock(vm, llm=[(r".*alpha-report.*", bad)])
        assert assess(vm, c, pid, "c1", 200) == "REJECTED"
        assert claim_state(vm, c, pid, "c1")["same"] == "unclear"


def test_a_claim_assessed_twice_is_refused(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    remock(vm, llm=[(r".*alpha-report.*", ans("true", "SHARD-7 cache shipped"))])
    assert assess(vm, c, pid, "c1", 200) == "CORROBORATED"
    before = full_snapshot(vm, c, pid, ["c1"])
    with pytest.raises(Exception):
        assess(vm, c, pid, "c1", 210)
    assert full_snapshot(vm, c, pid, ["c1"]) == before


# ==========================================================================
# E. the freeze boundary -- forced by the anti-collusion rule
# ==========================================================================


def test_assess_before_the_freeze_is_refused(pool):
    """The anti-collusion rule cannot be applied to a set that can still grow,
    so nothing is judged until the claim set is final."""
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    before = full_snapshot(vm, c, pid, ["c1"])
    for t in (10, 50, 99):
        with pytest.raises(Exception):
            assess(vm, c, pid, "c1", t)
    assert full_snapshot(vm, c, pid, ["c1"]) == before


def test_claims_filed_after_the_freeze_cannot_change_the_set(pool):
    """A pool judged on a frozen set cannot be reshaped by a late claim."""
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    remock(vm, llm=[(r".*alpha-report.*", ans("false", ""))])
    assert assess(vm, c, pid, "c1", 200) == "REJECTED"
    with pytest.raises(Exception):
        file_claim(vm, c, pid, "c2", ANCHOR, pair(URL_CHARLIE, URL_DELTA), 250,
                   sender=CLAIMANT_B)
    assert [x["claim_id"] for x in pool_state(vm, c, pid)["claims"]] == ["c1"]


def test_assess_is_permissionless(pool):
    """Anyone may assess, not only the claimant or the funder, so a pool can
    never be stalled by a party who would rather it stayed unjudged."""
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    remock(vm, llm=[(r".*alpha-report.*", ans("true", "SHARD-7 cache shipped"))])
    for sender in (STRANGER, FUNDER, CLAIMANT_B):
        vm.warp(iso(200))
        vm.sender = sender
        # c1 is already judged by the time the next sender runs, so use a fresh
        # pool for each to prove the caller identity is irrelevant.
        pid2 = open_pool(vm, c)
        file_claim(vm, c, pid2, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
        vm.warp(iso(200))
        vm.sender = sender
        assert c.assess(pid2, "c1") == "CORROBORATED"


# ==========================================================================
# F. allocation and funds
# ==========================================================================


def test_nothing_corroborated_refunds_the_whole_pool(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    remock(vm, llm=[(r".*alpha-report.*", ans("false", ""))])
    assess(vm, c, pid, "c1", 200)
    before = balance(vm, FUNDER)
    held = contract_balance(vm)
    assert allocate(vm, c, pid, 300) == "SETTLED"
    assert balance(vm, FUNDER) == before + POOL
    assert contract_balance(vm) == held - POOL
    p = pool_state(vm, c, pid)
    assert p["paid_total"] == 0
    assert p["remainder"] == POOL


def test_one_corroborated_claim_takes_the_whole_pool(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    remock(vm, llm=[(r".*alpha-report.*", ans("true", "SHARD-7 cache shipped"))])
    assess(vm, c, pid, "c1", 200)
    before = balance(vm, CLAIMANT_A)
    assert allocate(vm, c, pid, 300) == "SETTLED"
    assert balance(vm, CLAIMANT_A) == before + POOL
    assert pool_state(vm, c, pid)["remainder"] == 0


def test_three_claims_leave_a_remainder_for_the_funder(pool):
    """Ten to the power of eighteen does not divide by three. The odd units
    have exactly one home, and this is the case that bit the last project."""
    vm, c = pool
    pid = open_pool(vm, c)
    claims = [("c1", CLAIMANT_A, URL_ALPHA, URL_BRAVO),
              ("c2", CLAIMANT_B, URL_CHARLIE, URL_WRAP),
              ("c3", CLAIMANT_C, URL_GOLF, URL_HOTEL)]
    remock(vm, llm=[
        pair_ans("alpha-report", "bravo-weekly", "true", "SHARD-7 cache shipped"),
        pair_ans("charlie-log", "foxtrot-mirror", "true", "SHARD-\n7 cache shipped"),
    ])
    # Two extra hosts serving the same two documents, so c3 rests on a third
    # distinct host pair rather than reusing c1's. Added after remock(), which
    # clears every mock first.
    for token, body in (("golf", "alpha-report 412. The SHARD-7 cache shipped on "
                                  "2026-01-05 and cut p95 latency to 120ms. "
                                  "Release signed off."),
                        ("hotel", "bravo-weekly 12. Notes on the SHARD-7 cache "
                                  "rollout on 2026-01-05; p95 latency is now "
                                  "120ms. Release signed off.")):
        vm.mock_web(".*" + token + "\\.example\\.com.*",
                    {"method": "GET", "status": 200, "body": body})
    for cid, who, u0, u1 in claims:
        file_claim(vm, c, pid, cid, ANCHOR, pair(u0, u1), 10, sender=who)
    for cid, who, u0, u1 in claims:
        assert assess(vm, c, pid, cid, 200) == "CORROBORATED"

    share, remainder = divmod(POOL, 3)
    assert remainder != 0, "the fixture must produce an indivisible remainder"

    before = {w: balance(vm, w) for _, w, _, _ in claims}
    fb = balance(vm, FUNDER)
    held = contract_balance(vm)
    assert allocate(vm, c, pid, 300) == "SETTLED"

    for cid, who, _, _ in claims:
        assert balance(vm, who) == before[who] + share
    assert balance(vm, FUNDER) == fb + remainder

    p = pool_state(vm, c, pid)
    assert p["share"] == share
    assert p["remainder"] == remainder
    assert p["paid_total"] == 3 * share
    assert p["paid_total"] + p["remainder"] == p["total"]
    assert contract_balance(vm) == held - POOL


def test_rejected_claims_get_nothing(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "good", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10,
               sender=CLAIMANT_A)
    file_claim(vm, c, pid, "bad", ANCHOR, pair(URL_ALPHA_2, URL_CHARLIE), 10,
               sender=CLAIMANT_B)
    remock(vm, llm=[
        pair_ans("alpha-report", "bravo-weekly", "true", "SHARD-7 cache shipped"),
        pair_ans("alpha-report", "charlie-log", "false", ""),
    ])
    assess(vm, c, pid, "good", 200)
    assess(vm, c, pid, "bad", 210)
    before_b = balance(vm, CLAIMANT_B)
    assert allocate(vm, c, pid, 300) == "SETTLED"
    assert balance(vm, CLAIMANT_B) == before_b
    assert claim_state(vm, c, pid, "bad")["reason"] == \
        "the two sources do not describe the same thing"


def test_every_unit_is_accounted_for(pool):
    """The identity this contract is built to hold, whatever happens."""
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10,
               sender=CLAIMANT_A)
    file_claim(vm, c, pid, "c2", ANCHOR, pair(URL_ALPHA_2, URL_CHARLIE), 10,
               sender=CLAIMANT_B)
    file_claim(vm, c, pid, "c3", ANCHOR, pair(URL_DELTA, URL_WRAP), 10,
               sender=CLAIMANT_C)
    remock(vm, llm=[
        pair_ans("alpha-report", "bravo-weekly", "true", "SHARD-7 cache shipped"),
        pair_ans("alpha-report", "charlie-log", "false", ""),
        pair_ans("delta-notes", "foxtrot-mirror", "false", ""),
    ])
    assess(vm, c, pid, "c1", 200)
    assess(vm, c, pid, "c2", 210)
    assess(vm, c, pid, "c3", 220)
    p = pool_state(vm, c, pid)
    assert [x["status"] for x in p["claims"]] == ["CORROBORATED", "REJECTED", "REJECTED"]

    held = contract_balance(vm)
    allocate(vm, c, pid, 300)
    p = pool_state(vm, c, pid)
    assert p["paid_total"] + p["remainder"] == p["total"] == POOL
    assert contract_balance(vm) == held - POOL


def test_allocate_needs_every_claim_assessed(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    with pytest.raises(Exception):
        allocate(vm, c, pid, 300)
    remock(vm, llm=[(r".*alpha-report.*", ans("true", "SHARD-7 cache shipped"))])
    assess(vm, c, pid, "c1", 200)
    assert allocate(vm, c, pid, 300) == "SETTLED"


def test_allocate_is_pure_arithmetic(pool):
    """No model is asked anything at all here, so no model mock is installed.
    An unexpected call would fail the test."""
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    remock(vm, llm=[(r".*alpha-report.*", ans("true", "SHARD-7 cache shipped"))])
    assess(vm, c, pid, "c1", 200)
    remock(vm)                                  # strip every model mock
    assert allocate(vm, c, pid, 300) == "SETTLED"


def test_cancel_refunds_only_before_any_claim(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    before = balance(vm, FUNDER)
    held = contract_balance(vm)
    vm.warp(iso(20))
    vm.sender = FUNDER
    assert c.cancel(pid) == "REFUNDED"
    assert balance(vm, FUNDER) == before + POOL
    assert contract_balance(vm) == held - POOL

    pid2 = open_pool(vm, c)
    file_claim(vm, c, pid2, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    vm.warp(iso(30))
    vm.sender = FUNDER
    with pytest.raises(Exception):
        c.cancel(pid2)
    assert pool_state(vm, c, pid2)["status"] == "OPEN"


def test_cancel_is_funder_only(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    for sender in (STRANGER, CLAIMANT_A, ""):
        vm.warp(iso(20))
        vm.sender = sender
        with pytest.raises(Exception):
            c.cancel(pid)
    vm.sender = FUNDER
    assert c.cancel(pid) == "REFUNDED"


def test_the_pool_goes_read_only_once_settled(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    remock(vm, llm=[(r".*alpha-report.*", ans("true", "SHARD-7 cache shipped"))])
    assess(vm, c, pid, "c1", 200)
    assert allocate(vm, c, pid, 300) == "SETTLED"
    before = full_snapshot(vm, c, pid, ["c1"])
    for call in (
        lambda: file_claim(vm, c, pid, "c2", ANCHOR, pair(URL_CHARLIE, URL_DELTA), 310,
                           sender=CLAIMANT_B),
        lambda: assess(vm, c, pid, "c1", 310),
        lambda: allocate(vm, c, pid, 310),
        lambda: c.cancel(pid),
    ):
        with pytest.raises(Exception):
            call()
    assert full_snapshot(vm, c, pid, ["c1"]) == before


# ==========================================================================
# G. uniform write preconditions
# ==========================================================================


def test_every_refusal_leaves_the_state_byte_identical(pool):
    """All five writes enforce the same preconditions, and none of them
    mutates anything when it refuses."""
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)

    cases = [
        ("file after the freeze",
         lambda: file_claim(vm, c, pid, "c2", ANCHOR, pair(URL_CHARLIE, URL_DELTA), 200,
                            sender=CLAIMANT_B)),
        ("file the same id twice",
         lambda: file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_CHARLIE, URL_DELTA), 10)),
        ("file one source on its own host",
         lambda: file_claim(vm, c, pid, "c2", ANCHOR, pair(URL_ALPHA, URL_ALPHA_2), 10)),
        ("file a pair already in use",
         lambda: file_claim(vm, c, pid, "c2", ANCHOR, pair(URL_BRAVO, URL_ALPHA), 10)),
        ("file to a missing pool",
         lambda: file_claim(vm, c, "ghost", "c2", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)),
        ("assess before the freeze", lambda: assess(vm, c, pid, "c1", 50)),
        ("assess a missing claim", lambda: assess(vm, c, pid, "ghost", 200)),
        ("allocate before the freeze", lambda: allocate(vm, c, pid, 50)),
    ]
    for label, call in cases:
        before = full_snapshot(vm, c, pid, ["c1"])
        with pytest.raises(Exception):
            call()
        assert full_snapshot(vm, c, pid, ["c1"]) == before, label

    for sender, call in ((STRANGER, lambda: c.cancel(pid)),
                         (STRANGER, lambda: c.withdraw(pid, "c1"))):
        vm.sender = sender
        before = full_snapshot(vm, c, pid, ["c1"])
        with pytest.raises(Exception):
            call()
        assert full_snapshot(vm, c, pid, ["c1"]) == before


# ==========================================================================
# H. views
# ==========================================================================


def test_views_return_strings_never_structures(pool):
    """A bare float or list in a return value breaks calldata encoding on chain
    while direct mode stays green, so the type is part of the contract."""
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    for value in (c.get_pool(pid), c.get_claim(pid, "c1")):
        assert isinstance(value, str)
        json.loads(value)
    assert isinstance(c.get_pool_count(), int)


def test_get_pool_count_tracks_opens(pool):
    vm, c = pool
    assert c.get_pool_count() == 0
    open_pool(vm, c)
    assert c.get_pool_count() == 1
    open_pool(vm, c)
    assert c.get_pool_count() == 2


def test_unknown_pool_or_claim_raises(pool):
    vm, c = pool
    pid = open_pool(vm, c)
    for call in (lambda: c.get_pool("ghost"),
                 lambda: c.get_claim(pid, "ghost"),
                 lambda: c.get_claim("ghost", "c1"),
                 lambda: c.assess("ghost", "c1"),
                 lambda: c.allocate("ghost"),
                 lambda: c.cancel("ghost"),
                 lambda: c.withdraw("ghost", "c1"),
                 lambda: file_claim(vm, c, "ghost", "c1", ANCHOR,
                                    pair(URL_ALPHA, URL_BRAVO), 10)):
        with pytest.raises(Exception):
            call()


def test_get_pool_lists_every_claim_with_its_owner(pool):
    """A reviewer can see who filed what and how it ended up."""
    vm, c = pool
    pid = open_pool(vm, c)
    file_claim(vm, c, pid, "c1", ANCHOR, pair(URL_ALPHA, URL_BRAVO), 10)
    file_claim(vm, c, pid, "c2", ANCHOR, pair(URL_ALPHA_2, URL_CHARLIE), 10,
               sender=CLAIMANT_B)
    remock(vm, llm=[
        pair_ans("alpha-report", "bravo-weekly", "true", "SHARD-7 cache shipped"),
        pair_ans("alpha-report", "charlie-log", "false", ""),
    ])
    assess(vm, c, pid, "c1", 200)
    assess(vm, c, pid, "c2", 210)
    p = pool_state(vm, c, pid)
    assert [(x["claim_id"], x["status"], x["claimant"]) for x in p["claims"]] == [
        ("c1", "CORROBORATED", CLAIMANT_A),
        ("c2", "REJECTED", CLAIMANT_B),
    ]
