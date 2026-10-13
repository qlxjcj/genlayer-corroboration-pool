"""Fixtures for Corroboration Pool direct-mode tests.

Direct mode does not track native value flow, so two accounting hooks are
installed (mirroring what the chain does) so the tests can genuinely assert
fund movement:

1. payable value: `open_pool` moves `vm.value` sender -> contract
2. `emit_transfer` is intercepted as a PostMessage gl_call and moved
   contract -> recipient

Without them every payout assertion would be a tautology.

Time is driven explicitly with `vm.warp(iso)` so the claim freeze boundary is
tested deterministically. Every test states exactly what the model is expected
to answer, so an unexpected model call fails loudly.
"""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

CONTRACT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "corroboration_pool.py",
)

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)

FUNDER = "0x" + "aa" * 20
CLAIMANT_A = "0x" + "11" * 20
CLAIMANT_B = "0x" + "22" * 20
CLAIMANT_C = "0x" + "33" * 20
STRANGER = "0x" + "44" * 20
BAD_ADDR = "0x1234"

POOL = 10 ** 18
BRIEF = "Reward the SHARD-7 cache work that cut p95 latency."

ANCHOR = "SHARD-7"
ANCHOR_OTHER = "QUOTA-2"

# --- evidence documents. The report token is what the model mock keys on, and
# no token is a substring of another so first-match-wins cannot bleed one
# fixture into another. ---
BODY_ALPHA = ("alpha-report 412. The SHARD-7 cache shipped on 2026-01-05 and cut "
              "p95 latency to 120ms. Release signed off.")
BODY_BRAVO = ("bravo-weekly 12. Notes on the SHARD-7 cache rollout on 2026-01-05; "
              "p95 latency is now 120ms. Release signed off.")
BODY_CHARLIE = "charlie-log 3. The SHARD-7 cache shipped on 2026-01-05. Nothing else to report."
BODY_DELTA = "delta-notes 9. Weather was sunny all week at the depot. No shipment recorded."
BODY_ECHO = "echo-snapshot 11. Uptime held at 99.9% for the QUOTA-2 rollout."
BODY_WRAP = ("foxtrot-mirror 7. The SHARD-\n7 cache shipped on 2026-01-05. "
             "p95 latency to 120ms.")
BODY_EMPTY = ""
BODY_ERROR = "Internal Server Error"

URL_ALPHA = "https://alpha.example.com/doc"
URL_ALPHA_2 = "https://alpha.example.com/other"
URL_BRAVO = "https://bravo.example.com/doc"
URL_BRAVO_2 = "https://bravo.example.com/other"
URL_CHARLIE = "https://charlie.example.com/doc"
URL_DELTA = "https://delta.example.com/doc"
URL_ECHO = "https://echo.example.com/doc"
URL_WRAP = "https://foxtrot.example.com/doc"
URL_EMPTY = "https://empty.example.com/doc"
URL_ERROR = "https://error.example.com/doc"
URL_FTP = "ftp://alpha.example.com/doc"

# Same host as URL_ALPHA once scheme, port, path and userinfo are stripped.
URL_ALPHA_PORT = "https://alpha.example.com:8443/deep/path?x=1"
URL_ALPHA_USER = "https://user:secret@alpha.example.com/doc"


def iso(offset: int) -> str:
    return (BASE + timedelta(seconds=offset)).isoformat()


def balance(vm, addr):
    return vm._balances.get(vm._to_bytes(addr), 0)


def contract_balance(vm):
    return vm._balances.get(vm._contract_address, 0)


def ans(same, shared=""):
    return json.dumps({"same": same, "shared": shared})


def remock(vm, llm=None):
    """Install web mocks plus exactly the model answers the test expects.

    There is deliberately no catch-all model mock: a call the test did not
    anticipate must fail rather than silently return something plausible."""
    vm.clear_mocks()
    for token, status, body in (
        ("alpha", 200, BODY_ALPHA),
        ("bravo", 200, BODY_BRAVO),
        ("charlie", 200, BODY_CHARLIE),
        ("delta", 200, BODY_DELTA),
        ("echo", 200, BODY_ECHO),
        ("foxtrot", 200, BODY_WRAP),
        ("empty", 200, BODY_EMPTY),
        ("error", 500, BODY_ERROR),
    ):
        vm.mock_web(".*" + token + "\\.example\\.com.*",
                    {"method": "GET", "status": status, "body": body})
    for pattern, response in (llm or []):
        vm.mock_llm(pattern, response)


@pytest.fixture
def pool(direct_vm, direct_deploy):
    vm = direct_vm

    def _value_transfer_hook(vm, request):
        if "PostMessage" not in request:
            return None
        msg = request["PostMessage"]
        amount = int(msg.get("value", 0))
        if amount > 0:
            contract = vm._contract_address
            recipient = vm._to_bytes(msg["address"])
            vm._balances[contract] = vm._balances.get(contract, 0) - amount
            vm._balances[recipient] = vm._balances.get(recipient, 0) + amount
        return {"ok": None}

    vm._gl_call_hook = _value_transfer_hook

    remock(vm)
    c = direct_deploy(CONTRACT)

    def _wrap(fn):
        def inner(*args):
            if vm.value > 0:
                sender = vm._to_bytes(vm.sender)
                contract = vm._contract_address
                vm._balances[sender] = vm._balances.get(sender, 0) - vm.value
                vm._balances[contract] = vm._balances.get(contract, 0) + vm.value
            return fn(*args)
        return inner

    c.open_pool = _wrap(c.open_pool)

    for addr in (FUNDER, CLAIMANT_A, CLAIMANT_B, CLAIMANT_C, STRANGER):
        vm.deal(addr, 1000 * POOL)

    vm.warp(iso(0))
    return vm, c


def open_pool(vm, c, window=100, total=POOL, brief=BRIEF, sender=FUNDER, value=None):
    vm.warp(iso(0))
    vm.sender = sender
    vm.value = value if value is not None else total
    pid = c.open_pool(brief, window)
    vm.value = 0
    return pid


def file_claim(vm, c, pid, cid, anchor, sources, t, sender=CLAIMANT_A):
    vm.warp(iso(t))
    vm.sender = sender
    return c.file_claim(pid, cid, anchor, sources)


def assess(vm, c, pid, cid, t, sender=STRANGER):
    vm.warp(iso(t))
    vm.sender = sender
    return c.assess(pid, cid)


def allocate(vm, c, pid, t, sender=STRANGER):
    vm.warp(iso(t))
    vm.sender = sender
    return c.allocate(pid)


def claim_state(vm, c, pid, cid):
    return json.loads(c.get_claim(pid, cid))


def pool_state(vm, c, pid):
    return json.loads(c.get_pool(pid))


def full_snapshot(vm, c, pid, cids):
    parts = [c.get_pool(pid)]
    for cid in cids:
        parts.append(c.get_claim(pid, cid))
    return parts
