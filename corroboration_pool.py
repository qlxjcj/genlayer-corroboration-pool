# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
import json
from genlayer import *

MAX_BRIEF = 400
MAX_ANCHOR = 120
MAX_ID = 32
MAX_CLAIMS = 12
MAX_ANCHORS = 4
MAX_HOSTS = 10
MIN_WINDOW = 1

OPEN = "OPEN"
FROZEN = "FROZEN"
SETTLED = "SETTLED"
REFUNDED = "REFUNDED"

FILED = "FILED"
CORROBORATED = "CORROBORATED"
REJECTED = "REJECTED"
WITHDRAWN = "WITHDRAWN"

SPACE = " \t\r\n\f\v"


class CorroborationPool(gl.Contract):
    """One fund, shared only by claims that two independent sources back.

    The funder fixes the question and the venues: the anchors to corroborate
    and the hosts trusted as independent places to look. A claim picks one
    anchor and two sources from two different trusted hosts, and is paid only
    when the anchor is in both and consensus agrees. See README."""

    pools: TreeMap[str, str]
    claims: TreeMap[str, str]
    pool_count: u256

    def __init__(self):
        self.pool_count = 0

    # ---------------- helpers ----------------

    def _addr_hex(self, a) -> str:
        if isinstance(a, str):
            return a
        h = getattr(a, "as_hex", None)
        if isinstance(h, str):
            return h
        if isinstance(a, (bytes, bytearray)):
            return "0x" + bytes(a).hex()
        return str(a)

    def _is_valid_address(self, addr) -> bool:
        if not isinstance(addr, str) or not addr.startswith("0x") or len(addr) != 42:
            return False
        try:
            int(addr[2:], 16)
        except ValueError:
            return False
        return True

    def _iso_to_epoch(self, s: str) -> int:
        s = s.strip()
        if len(s) < 19:
            return 0
        offset = 0
        tail = s[19:]
        if tail.endswith("Z"):
            tail = tail[:-1]
        if tail and (tail[0] == "+" or tail[0] == "-"):
            try:
                offset = (1 if tail[0] == "+" else -1) * (int(tail[1:3]) * 3600 + int(tail[4:6]) * 60)
            except (ValueError, IndexError):
                offset = 0
        try:
            y, mo, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
            hh, mm, ss = int(s[11:13]), int(s[14:16]), int(s[17:19])
        except (ValueError, IndexError):
            return 0
        if not (1 <= mo <= 12 and 1 <= d <= 31 and hh < 24 and mm < 60 and ss < 61):
            return 0
        yy = y - 1 if mo <= 2 else y
        era = yy // 400
        yoe = yy - era * 400
        doy = (153 * (mo + (-3 if mo > 2 else 9)) + 2) // 5 + d - 1
        doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
        return (era * 146097 + doe - 719468) * 86400 + hh * 3600 + mm * 60 + ss - offset

    def _now(self) -> int:
        raw = getattr(gl, "message_raw", None)
        d = None
        if raw is not None:
            try:
                d = raw["datetime"]
            except Exception:
                d = None
        if d is None:
            d = getattr(gl.message, "datetime", None)
        if d is None:
            return 0
        return self._iso_to_epoch(d if isinstance(d, str) else str(d))

    def _squash(self, text: str) -> str:
        """lowercase, every blank removed: survives line wrap and stray padding."""
        out = []
        for ch in str(text).lower():
            if ch in SPACE:
                continue
            out.append(ch)
        return "".join(out)

    def _host(self, url: str) -> str:
        """scheme://host/path -> host, lowercased, no port or userinfo."""
        u = str(url).strip().lower()
        i = u.find("://")
        if i >= 0:
            u = u[i + 3:]
        for ch in "/?#":
            j = u.find(ch)
            if j >= 0:
                u = u[:j]
        k = u.rfind("@")
        if k >= 0:
            u = u[k + 1:]
        c = u.rfind(":")
        if c >= 0:
            u = u[:c]
        return u

    def _decode_body(self, content) -> str:
        body = getattr(content, "body", None)
        if body is None:
            return str(content)
        return body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)

    def _transfer(self, recipient: Address, amount: int):
        if amount > 0:
            gl.get_contract_at(recipient).emit_transfer(value=u256(amount))

    def _load_pool(self, pool_id: str) -> dict:
        raw = self.pools.get(str(pool_id), "")
        if not raw:
            raise gl.vm.UserError("Pool not found")
        return json.loads(raw)

    def _save_pool(self, p: dict):
        self.pools[p["pool_id"]] = json.dumps(p)

    def _ckey(self, pool_id: str, claim_id: str) -> str:
        return str(pool_id) + "|" + str(claim_id)

    def _load_claim(self, pool_id: str, claim_id: str) -> dict:
        raw = self.claims.get(self._ckey(pool_id, claim_id), "")
        if not raw:
            raise gl.vm.UserError("Claim not found")
        return json.loads(raw)

    def _save_claim(self, pool_id: str, c: dict):
        self.claims[self._ckey(pool_id, c["claim_id"])] = json.dumps(c)

    def _claim_ids(self, p: dict) -> list:
        try:
            return json.loads(p["claim_ids"])
        except (json.JSONDecodeError, TypeError):
            return []

    # ---------------- corroboration ----------------

    def _anchor_in(self, body: str, anchor: str) -> bool:
        # The empty-string trap: '' is a substring of absolutely everything.
        m = self._squash(anchor)
        if not m:
            return False
        if not self._squash(body):
            return False
        return self._norm(anchor) in self._norm(body) or m in self._squash(body)

    def _norm(self, text: str) -> str:
        return " ".join(str(text).lower().split())

    def _corroborated(self, body_a: str, body_b: str, anchor: str, res: dict) -> bool:
        # The model can only lose credit here, never create it.
        if not self._anchor_in(body_a, anchor):
            return False
        if not self._anchor_in(body_b, anchor):
            return False
        if str(res.get("same", "unclear")) != "true":
            return False
        shared = res.get("shared", "")
        s = self._squash(shared if isinstance(shared, str) else "")
        if not s:
            return False
        if self._squash(anchor) not in s:
            return False
        return s in self._squash(body_a) or s in self._squash(body_b)

    def _examine(self, urls: list, anchor: str) -> dict:
        """Fetch both documents; the verdict is computed in code, in the block."""

        def check() -> dict:
            bodies = []
            read = 0
            for u in urls:
                text = ""
                try:
                    text = self._decode_body(gl.nondet.web.render(u))
                except Exception:
                    text = ""
                if text.strip():
                    read += 1
                bodies.append(text)
            body_a, body_b = bodies[0], bodies[1]
            if read == 0:
                return {"retrieved": False, "same": "unclear", "shared": "",
                        "ok": False, "why": "no source could be read"}

            task = (
                "Two documents are offered as independent accounts of ONE contribution.\n"
                "Decide only whether they are about the same thing; do not judge quality.\n"
                "Return the single span naming the contribution that both share, copied\n"
                "exactly. Use an empty string when they are not about the same thing.\n\n"
                "DOC A:\n" + body_a[:1100] + "\n\nDOC B:\n" + body_b[:1100] +
                "\n\nANCHOR: " + anchor +
                '\n\nJSON only: {"same": "true"|"false"|"unclear", "shared": "<span or empty>"}'
            )
            # An answer the contract cannot use credits nothing, and the pool
            # still settles.
            parsed = None
            try:
                raw = gl.nondet.exec_prompt(task)
                if isinstance(raw, str):
                    parsed = json.loads(raw.replace("```json", "").replace("```", ""))
                elif isinstance(raw, dict):
                    parsed = raw
            except Exception:
                parsed = None
            if not isinstance(parsed, dict):
                parsed = {}
            same = str(parsed.get("same", "unclear")).strip().lower()
            if same not in ("true", "false", "unclear"):
                same = "unclear"
            shared = parsed.get("shared")
            shared = str(shared) if isinstance(shared, str) else ""

            ok = self._corroborated(body_a, body_b, anchor, {"same": same, "shared": shared})
            if ok:
                why = "two independent sources carry the anchor and agree"
            elif not self._anchor_in(body_a, anchor) or not self._anchor_in(body_b, anchor):
                why = "the anchor is not in both sources"
            elif same != "true":
                why = "the two sources do not describe the same thing"
            else:
                why = "no shared span naming the anchor"
            return {"retrieved": True, "same": same, "shared": shared,
                    "ok": ok, "why": why}

        principle = ("Equivalent only if retrieved, ok and same match exactly; "
                     "shared wording may differ and empty stays empty.")
        return gl.eq_principle.prompt_comparative(check, principle)

    # ---------------- lifecycle ----------------

    @gl.public.write.payable
    def open_pool(self, brief: str, anchors: list, hosts: list, claim_window: int) -> str:
        """Open a pool: the funder names the anchors to corroborate and the hosts."""
        funder = self._addr_hex(gl.message.sender_address)
        total = int(gl.message.value)
        if not brief or not brief.strip() or len(brief) > MAX_BRIEF:
            raise gl.vm.UserError("Brief must be 1..400 chars")
        if int(claim_window) < MIN_WINDOW:
            raise gl.vm.UserError("Claim window must be > 0")
        if total <= 0:
            raise gl.vm.UserError("Pool must be > 0")

        alist = []
        if not isinstance(anchors, list) or not anchors or len(anchors) > MAX_ANCHORS:
            raise gl.vm.UserError("Anchors must be 1..4")
        for a in anchors:
            s = str(a).strip()
            if not s or len(s) > MAX_ANCHOR:
                raise gl.vm.UserError("Anchors must be 1..120 chars")
            if self._squash(s) in [self._squash(x) for x in alist]:
                raise gl.vm.UserError("Anchors must be distinct")
            alist.append(s)

        hlist = []
        if not isinstance(hosts, list) or len(hosts) < 2 or len(hosts) > MAX_HOSTS:
            raise gl.vm.UserError("Hosts must be 2..10")
        for h in hosts:
            hs = self._host(str(h))
            if not hs or "." not in hs:
                raise gl.vm.UserError("Hosts must look like hostnames")
            if hs in hlist:
                raise gl.vm.UserError("Hosts must be distinct")
            hlist.append(hs)

        pid = "p" + str(int(self.pool_count))
        self.pools[pid] = json.dumps({
            "pool_id": pid, "funder": funder, "total": total, "brief": brief.strip(),
            "anchors": alist, "hosts": hlist,
            "claim_by": self._now() + int(claim_window), "status": OPEN,
            "claim_ids": "[]", "corroborated_count": 0, "share": 0,
            "remainder": 0, "paid_total": 0,
        })
        self.pool_count = u256(int(self.pool_count) + 1)
        return pid

    @gl.public.write
    def file_claim(self, pool_id: str, claim_id: str, anchor: str, sources: list) -> str:
        """File a claim while the set is still open. Judgement is impossible
        here on purpose: the anti-collusion check needs the whole set."""
        p = self._load_pool(pool_id)
        if str(p["status"]) != OPEN:
            raise gl.vm.UserError("Pool is " + str(p["status"]))
        if self._now() >= int(p["claim_by"]):
            raise gl.vm.UserError("Claim window has closed")
        cid = str(claim_id).strip()
        if not cid or len(cid) > MAX_ID:
            raise gl.vm.UserError("Claim id must be short and non-empty")
        if self._ckey(pool_id, cid) in self.claims:
            raise gl.vm.UserError("Claim already filed")
        ids = self._claim_ids(p)
        if len(ids) >= MAX_CLAIMS:
            raise gl.vm.UserError("Too many claims")
        # The claimant may not choose the question. The anchor is filed back in
        # the funder's own wording, so two spellings cannot be two claims.
        want = self._squash(anchor)
        a = ""
        for x in p["anchors"]:
            if self._squash(str(x)) == want:
                a = str(x)
                break
        if not a:
            raise gl.vm.UserError("Anchor is not one the funder named")

        if not isinstance(sources, list) or len(sources) != 2:
            raise gl.vm.UserError("Exactly two sources are required")
        urls = []
        for u in sources:
            us = str(u).strip()
            if not (us.startswith("http://") or us.startswith("https://")):
                raise gl.vm.UserError("Sources must be http(s)")
            urls.append(us)
        if urls[0] == urls[1]:
            raise gl.vm.UserError("Sources must differ")
        h0, h1 = self._host(urls[0]), self._host(urls[1])
        if not h0 or not h1 or h0 == h1:
            raise gl.vm.UserError("Sources must be from different hosts")
        # Nor the venue: a host the funder did not name may be the claimant's
        # own, and its own two sites agreeing corroborate nothing.
        permit = [str(v) for v in p["hosts"]]
        if h0 not in permit or h1 not in permit:
            raise gl.vm.UserError("Host is not one the funder trusts")

        # Anti-collusion both ways: one claim per anchor per account, so no
        # single address can occupy the pool, and one host pair per pool.
        me = self._addr_hex(gl.message.sender_address).lower()
        for other in ids:
            o = self._load_claim(pool_id, other)
            if str(o["status"]) == WITHDRAWN:
                continue
            if str(o["claimant"]).lower() == me and self._squash(str(o["anchor"])) == self._squash(a):
                raise gl.vm.UserError("You already hold a claim on this anchor")
            oh = sorted([str(x) for x in o["hosts"]])
            if oh == sorted([h0, h1]):
                raise gl.vm.UserError("That host pair already backs a claim")

        self._save_claim(pool_id, {
            "claim_id": cid, "claimant": self._addr_hex(gl.message.sender_address),
            "anchor": a, "sources": urls, "hosts": [h0, h1],
            "status": FILED, "reason": "", "same": "unclear", "shared": "",
        })
        p["claim_ids"] = json.dumps(ids + [cid])
        self._save_pool(p)
        return FILED

    @gl.public.write
    def withdraw(self, pool_id: str, claim_id: str) -> str:
        """A claimant may stand down before the freeze."""
        p = self._load_pool(pool_id)
        c = self._load_claim(pool_id, claim_id)
        if self._addr_hex(gl.message.sender_address).lower() != str(c["claimant"]).lower():
            raise gl.vm.UserError("Only the claimant withdraws")
        if str(p["status"]) != OPEN:
            raise gl.vm.UserError("Pool is " + str(p["status"]))
        if self._now() >= int(p["claim_by"]):
            raise gl.vm.UserError("Claim window has closed")
        if str(c["status"]) != FILED:
            raise gl.vm.UserError("Claim is " + str(c["status"]))
        c["status"] = WITHDRAWN
        c["reason"] = "withdrawn by the claimant"
        self._save_claim(pool_id, c)
        return WITHDRAWN

    @gl.public.write
    def assess(self, pool_id: str, claim_id: str) -> str:
        """Judge one claim, only once the claim set is final."""
        p = self._load_pool(pool_id)
        c = self._load_claim(pool_id, claim_id)
        if str(p["status"]) not in (OPEN, FROZEN):
            raise gl.vm.UserError("Pool is " + str(p["status"]))
        if self._now() < int(p["claim_by"]):
            raise gl.vm.UserError("Claim window is still open")
        if str(c["status"]) != FILED:
            raise gl.vm.UserError("Claim is " + str(c["status"]))

        res = self._examine([str(c["sources"][0]), str(c["sources"][1])], str(c["anchor"]))
        if not isinstance(res, dict):
            res = {}
        c["same"] = str(res.get("same", "unclear"))
        c["shared"] = str(res.get("shared", ""))[:200]
        c["status"] = CORROBORATED if bool(res.get("ok", False)) else REJECTED
        c["reason"] = str(res.get("why", "")) or "the claim is not corroborated"
        self._save_claim(pool_id, c)
        return str(c["status"])

    @gl.public.write
    def allocate(self, pool_id: str) -> str:
        """Split the fund: pure arithmetic over the frozen, assessed set."""
        p = self._load_pool(pool_id)
        if str(p["status"]) not in (OPEN, FROZEN):
            raise gl.vm.UserError("Pool is " + str(p["status"]))
        if self._now() < int(p["claim_by"]):
            raise gl.vm.UserError("Claim window is still open")
        ids = self._claim_ids(p)
        for cid in ids:
            if str(self._load_claim(pool_id, cid)["status"]) == FILED:
                raise gl.vm.UserError("Claim " + cid + " is not assessed")

        p["status"] = FROZEN
        winners = [cid for cid in ids
                   if str(self._load_claim(pool_id, cid)["status"]) == CORROBORATED]
        total = int(p["total"])
        if not winners:
            # Nothing survived corroboration, so the whole fund goes home.
            p["share"] = 0
            p["remainder"] = total
            p["paid_total"] = 0
            p["status"] = SETTLED
            self._save_pool(p)
            self._transfer(Address(p["funder"]), total)
            return SETTLED

        share = total // len(winners)
        # Whatever the split cannot divide still needs a home: the funder.
        remainder = total - share * len(winners)
        paid = 0
        for cid in winners:
            c = self._load_claim(pool_id, cid)
            self._transfer(Address(c["claimant"]), share)
            paid += share
        p["share"] = share
        p["remainder"] = remainder
        p["paid_total"] = paid
        p["corroborated_count"] = len(winners)
        p["status"] = SETTLED
        self._save_pool(p)
        self._transfer(Address(p["funder"]), remainder)
        return SETTLED

    @gl.public.write
    def cancel(self, pool_id: str) -> str:
        p = self._load_pool(pool_id)
        if str(p["status"]) != OPEN:
            raise gl.vm.UserError("Pool is " + str(p["status"]))
        if self._addr_hex(gl.message.sender_address).lower() != str(p["funder"]).lower():
            raise gl.vm.UserError("Only the funder cancels")
        if self._claim_ids(p):
            raise gl.vm.UserError("Claims have already been filed")
        p["status"] = REFUNDED
        self._save_pool(p)
        self._transfer(Address(p["funder"]), int(p["total"]))
        return REFUNDED

    # ---------------- views ----------------

    @gl.public.view
    def get_pool(self, pool_id: str) -> str:
        p = self._load_pool(pool_id)
        out = {k: p[k] for k in ("pool_id", "funder", "total", "brief", "anchors",
                                 "hosts", "claim_by", "status", "corroborated_count",
                                 "share", "remainder", "paid_total")}
        out["claims"] = [{"claim_id": cid,
                          "status": str(self._load_claim(pool_id, cid)["status"]),
                          "claimant": str(self._load_claim(pool_id, cid)["claimant"])}
                         for cid in self._claim_ids(p)]
        return json.dumps(out)

    @gl.public.view
    def get_claim(self, pool_id: str, claim_id: str) -> str:
        return json.dumps(self._load_claim(pool_id, claim_id))

    @gl.public.view
    def get_pool_count(self) -> int:
        return int(self.pool_count)
