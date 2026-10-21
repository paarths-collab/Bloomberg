"""Guest-token issuance rate limiting (POST /api/auth/guest)."""
import threading

import pytest
from httpx import ASGITransport, AsyncClient

from backend.auth import rate_limit
from backend.auth.rate_limit import SlidingWindowLimiter, reset_guest_limiter
from backend.main import app

URL = "/api/auth/guest"


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock():
    fake = FakeClock()
    reset_guest_limiter(clock=fake)
    return fake


@pytest.fixture
def limited(monkeypatch, clock):
    monkeypatch.setenv("AUTH_GUEST_RATE_LIMIT", "20")
    monkeypatch.setenv("AUTH_GUEST_RATE_WINDOW_SECONDS", "3600")
    monkeypatch.setenv("AUTH_GUEST_GLOBAL_LIMIT", "2000")
    monkeypatch.delenv("AUTH_TRUST_PROXY", raising=False)


def make_client(host="203.0.113.7"):
    return AsyncClient(
        transport=ASGITransport(app=app, client=(host, 5000)), base_url="http://test"
    )


async def test_21st_request_from_one_client_is_429(limited, clock):
    async with make_client() as c:
        for _ in range(20):
            assert (await c.post(URL)).status_code == 200
        resp = await c.post(URL)
    assert resp.status_code == 429
    assert resp.json() == {"detail": "Too many requests. Please try again later."}
    assert int(resp.headers["Retry-After"]) == 3600


async def test_defaults_are_on_without_env(monkeypatch, clock):
    for name in ("AUTH_GUEST_RATE_LIMIT", "AUTH_GUEST_RATE_WINDOW_SECONDS", "AUTH_GUEST_GLOBAL_LIMIT",
                 "AUTH_TRUST_PROXY"):
        monkeypatch.delenv(name, raising=False)
    assert rate_limit.guest_rate_limit_config() == (20, 3600, 2000)
    async with make_client() as c:
        codes = [(await c.post(URL)).status_code for _ in range(21)]
    assert codes[:20] == [200] * 20 and codes[20] == 429


async def test_clients_are_independent(limited, clock):
    async with make_client("203.0.113.1") as a, make_client("203.0.113.2") as b:
        for _ in range(20):
            assert (await a.post(URL)).status_code == 200
        assert (await a.post(URL)).status_code == 429
        assert (await b.post(URL)).status_code == 200


async def test_window_expiry_and_retry_after(limited, clock):
    async with make_client() as c:
        for _ in range(10):
            assert (await c.post(URL)).status_code == 200
            clock.advance(10)  # 100s span in total
        for _ in range(10):
            assert (await c.post(URL)).status_code == 200
        blocked = await c.post(URL)
        assert blocked.status_code == 429
        # Oldest token was issued 100s ago -> frees up in 3500s.
        assert int(blocked.headers["Retry-After"]) == 3500

        clock.advance(3499)
        assert (await c.post(URL)).status_code == 429
        clock.advance(1)  # oldest token leaves the window; one slot frees
        assert (await c.post(URL)).status_code == 200
        assert (await c.post(URL)).status_code == 429
        clock.advance(3600)  # everything expired
        assert (await c.post(URL)).status_code == 200


async def test_rejected_requests_do_not_extend_the_block(limited, clock):
    async with make_client() as c:
        for _ in range(20):
            await c.post(URL)
        for _ in range(5):
            clock.advance(100)
            assert (await c.post(URL)).status_code == 429
        clock.advance(3100)  # 3600s after the first batch
        assert (await c.post(URL)).status_code == 200


async def test_global_ceiling(monkeypatch, limited, clock):
    monkeypatch.setenv("AUTH_GUEST_GLOBAL_LIMIT", "5")
    for i in range(5):
        async with make_client(f"198.51.100.{i}") as c:
            assert (await c.post(URL)).status_code == 200
    async with make_client("198.51.100.99") as c:
        resp = await c.post(URL)
    assert resp.status_code == 429 and int(resp.headers["Retry-After"]) >= 1
    clock.advance(3600)
    async with make_client("198.51.100.99") as c:
        assert (await c.post(URL)).status_code == 200


async def test_global_ceiling_alone_when_per_client_disabled(monkeypatch, limited, clock):
    monkeypatch.setenv("AUTH_GUEST_RATE_LIMIT", "0")
    monkeypatch.setenv("AUTH_GUEST_GLOBAL_LIMIT", "3")
    async with make_client() as c:
        codes = [(await c.post(URL)).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert get_tracked() == 0  # per-client tracking is off


def get_tracked():
    return rate_limit.get_guest_limiter().tracked_keys()


async def test_zero_disables_both(monkeypatch, clock):
    monkeypatch.setenv("AUTH_GUEST_RATE_LIMIT", "0")
    monkeypatch.setenv("AUTH_GUEST_GLOBAL_LIMIT", "0")
    async with make_client() as c:
        for _ in range(60):
            assert (await c.post(URL)).status_code == 200


async def test_config_is_read_at_request_time(monkeypatch, limited, clock):
    async with make_client() as c:
        monkeypatch.setenv("AUTH_GUEST_RATE_LIMIT", "2")
        assert [(await c.post(URL)).status_code for _ in range(3)] == [200, 200, 429]
        monkeypatch.setenv("AUTH_GUEST_RATE_LIMIT", "3")
        assert (await c.post(URL)).status_code == 200
        monkeypatch.setenv("AUTH_GUEST_RATE_WINDOW_SECONDS", "60")
        clock.advance(61)
        assert (await c.post(URL)).status_code == 200


@pytest.mark.parametrize("value", ["abc", "-5", "", "1.5"])
async def test_invalid_config_falls_back_to_defaults(monkeypatch, value, clock):
    monkeypatch.setenv("AUTH_GUEST_RATE_LIMIT", value)
    monkeypatch.setenv("AUTH_GUEST_RATE_WINDOW_SECONDS", value)
    monkeypatch.setenv("AUTH_GUEST_GLOBAL_LIMIT", value)
    assert rate_limit.guest_rate_limit_config() == (20, 3600, 2000)


async def test_x_forwarded_for_ignored_by_default(limited, clock):
    async with make_client() as c:
        for i in range(20):
            assert (await c.post(URL, headers={"X-Forwarded-For": f"10.0.0.{i}"})).status_code == 200
        # spoofed rotating header did not buy fresh quota
        assert (await c.post(URL, headers={"X-Forwarded-For": "10.0.1.1"})).status_code == 429


async def test_x_forwarded_for_ignored_when_trust_not_exactly_one(monkeypatch, limited, clock):
    monkeypatch.setenv("AUTH_TRUST_PROXY", "true")
    async with make_client() as c:
        for i in range(20):
            await c.post(URL, headers={"X-Forwarded-For": f"10.0.0.{i}"})
        assert (await c.post(URL, headers={"X-Forwarded-For": "10.0.1.1"})).status_code == 429


async def test_x_forwarded_for_hops_1_uses_rightmost_entry(monkeypatch, limited, clock):
    monkeypatch.setenv("AUTH_TRUST_PROXY", "1")  # hops default 1
    async with make_client("10.9.9.9") as proxy:  # all requests arrive from the proxy
        for i in range(20):
            # attacker rotates the spoofed leading entries; the proxy appended the real client last
            r = await proxy.post(URL, headers={"X-Forwarded-For": f"10.0.0.{i}, 198.51.100.1"})
            assert r.status_code == 200
        blocked = await proxy.post(URL, headers={"X-Forwarded-For": "10.0.1.1, 198.51.100.1"})
        assert blocked.status_code == 429
        # a different original client behind the same proxy is independent
        assert (await proxy.post(URL, headers={"X-Forwarded-For": "198.51.100.2"})).status_code == 200
        # IPv6 clients work too
        assert (await proxy.post(URL, headers={"X-Forwarded-For": "2001:db8::1"})).status_code == 200


async def test_x_forwarded_for_hops_2_uses_second_from_right(monkeypatch, limited, clock):
    monkeypatch.setenv("AUTH_TRUST_PROXY", "1")
    monkeypatch.setenv("AUTH_TRUST_PROXY_HOPS", "2")
    async with make_client("10.9.9.9") as proxy:
        for i in range(20):
            # client -> edge proxy (appends client) -> app proxy (appends edge); spoofed junk leads
            hdr = {"X-Forwarded-For": f"10.0.0.{i}, 198.51.100.1, 172.16.0.5"}
            assert (await proxy.post(URL, headers=hdr)).status_code == 200
        same = {"X-Forwarded-For": "10.0.5.5, 198.51.100.1, 172.16.0.5"}
        assert (await proxy.post(URL, headers=same)).status_code == 429
        other = {"X-Forwarded-For": "10.0.5.5, 198.51.100.2, 172.16.0.5"}
        assert (await proxy.post(URL, headers=other)).status_code == 200


async def test_multiple_forwarded_for_header_lines_are_combined(monkeypatch, limited, clock):
    monkeypatch.setenv("AUTH_TRUST_PROXY", "1")
    monkeypatch.setenv("AUTH_TRUST_PROXY_HOPS", "2")
    async with make_client("10.9.9.9") as proxy:
        hdrs = [("X-Forwarded-For", "9.9.9.9, 198.51.100.1"), ("X-Forwarded-For", "172.16.0.5")]
        for _ in range(20):
            assert (await proxy.post(URL, headers=hdrs)).status_code == 200
        assert (await proxy.post(URL, headers=hdrs)).status_code == 429


async def test_too_few_forwarded_entries_fall_back_to_peer(monkeypatch, limited, clock):
    monkeypatch.setenv("AUTH_TRUST_PROXY", "1")
    monkeypatch.setenv("AUTH_TRUST_PROXY_HOPS", "3")
    async with make_client("10.9.9.9") as proxy:
        for i in range(20):
            hdr = {"X-Forwarded-For": f"198.51.100.{i}, 172.16.0.5"}  # only 2 entries, 3 trusted hops
            assert (await proxy.post(URL, headers=hdr)).status_code == 200
        assert (await proxy.post(URL, headers={"X-Forwarded-For": "198.51.100.200"})).status_code == 429


@pytest.mark.parametrize("value", ["0", "-1", "abc", ""])
def test_invalid_hops_fall_back_to_one(monkeypatch, value):
    monkeypatch.setenv("AUTH_TRUST_PROXY_HOPS", value)
    assert rate_limit._trusted_hops() == 1


async def test_trusted_proxy_with_garbage_header_uses_peer(monkeypatch, limited, clock):
    monkeypatch.setenv("AUTH_TRUST_PROXY", "1")
    async with make_client("10.9.9.9") as proxy:
        for i in range(20):
            assert (await proxy.post(URL, headers={"X-Forwarded-For": f"junk-{i}"})).status_code == 200
        assert (await proxy.post(URL, headers={"X-Forwarded-For": "junk-new"})).status_code == 429
        # no header at all -> still keyed on the peer
        assert (await proxy.post(URL)).status_code == 429


@pytest.mark.parametrize("raw, expected", [
    ("203.0.113.7", "203.0.113.7"),                    # IPv4 unaffected
    ("::ffff:203.0.113.7", "203.0.113.7"),             # IPv4-mapped -> IPv4
    ("[::ffff:203.0.113.7]", "203.0.113.7"),
    ("2001:db8:1:2:3:4:5:6", "2001:db8:1:2::/64"),     # IPv6 -> /64
    ("2001:db8:1:2:ffff:ffff:ffff:ffff", "2001:db8:1:2::/64"),
    ("fe80::1%eth0", "fe80::/64"),                     # zone id stripped
    ("fe80::1%25eth0", "fe80::/64"),                   # anything after % is dropped
    ("not-an-ip", None),
    ("", None),
])
def test_normalize_ip(raw, expected):
    assert rate_limit._normalize_ip(raw) == expected


async def test_peer_ipv6_grouped_by_slash_64(limited, clock):
    async with make_client("2001:db8:1:2::1") as a, make_client("2001:db8:1:2:aaaa:bbbb:cccc:dddd") as b, \
            make_client("2001:db8:1:3::1") as other:
        for _ in range(20):
            assert (await a.post(URL)).status_code == 200
        assert (await b.post(URL)).status_code == 429  # same /64 -> same key
        assert (await other.post(URL)).status_code == 200  # different /64


async def test_peer_ipv4_mapped_ipv6_shares_ipv4_key(limited, clock):
    async with make_client("203.0.113.7") as v4, make_client("::ffff:203.0.113.7") as mapped:
        for _ in range(20):
            assert (await v4.post(URL)).status_code == 200
        assert (await mapped.post(URL)).status_code == 429


async def test_forwarded_ipv6_zone_and_mapped_and_slash_64(monkeypatch, limited, clock):
    monkeypatch.setenv("AUTH_TRUST_PROXY", "1")
    async with make_client("10.9.9.9") as proxy:
        for i in range(10):
            assert (await proxy.post(URL, headers={"X-Forwarded-For": f"2001:db8:9:9::{i + 1}"})).status_code == 200
        for i in range(10):
            assert (await proxy.post(URL, headers={"X-Forwarded-For": f"2001:db8:9:9:{i + 1}::1%eth0"})).status_code == 200
        assert (await proxy.post(URL, headers={"X-Forwarded-For": "2001:db8:9:9:ffff::1"})).status_code == 429
        # IPv4-mapped forwarded entries share the plain IPv4 key
        for _ in range(20):
            assert (await proxy.post(URL, headers={"X-Forwarded-For": "198.51.100.9"})).status_code == 200
        assert (await proxy.post(URL, headers={"X-Forwarded-For": "::ffff:198.51.100.9"})).status_code == 429


async def test_unknown_client_skips_per_key_limit_but_global_applies(monkeypatch, limited, clock, caplog):
    monkeypatch.setenv("AUTH_GUEST_GLOBAL_LIMIT", "25")
    monkeypatch.setattr(rate_limit, "_warned_unknown_client", False)
    transport = ASGITransport(app=app, client=None)
    with caplog.at_level("WARNING", logger=rate_limit.logger.name):
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            codes = [(await c.post(URL)).status_code for _ in range(26)]
    assert codes[:25] == [200] * 25 and codes[25] == 429  # 20/hour per-key cap not applied
    assert get_tracked() == 0
    assert sum("without a client address" in r.getMessage() for r in caplog.records) == 1


def test_retry_after_is_max_of_key_and_global_waits():
    clk = FakeClock(0)
    lim = SlidingWindowLimiter(clock=clk)
    # Case 1: per-key wait (80) exceeds global wait (30).
    lim.check("B", limit=0, window=100, global_limit=3)  # t=0 (global only)
    clk.now = 50
    lim.check("A", limit=2, window=100, global_limit=3)
    clk.now = 60
    lim.check("A", limit=2, window=100, global_limit=3)
    clk.now = 70
    assert lim.check("A", limit=2, window=100, global_limit=3) == 80  # key: 50+100-70; global: 0+100-70
    # Case 2: global wait (80) exceeds per-key wait (30).
    lim = SlidingWindowLimiter(clock=clk)
    clk.now = 0
    lim.check("A", limit=2, window=100, global_limit=0)  # per-key only
    clk.now = 1
    lim.check("A", limit=2, window=100, global_limit=0)
    clk.now = 50
    lim.check("B", limit=0, window=100, global_limit=2)  # global only
    clk.now = 60
    lim.check("C", limit=0, window=100, global_limit=2)
    clk.now = 70
    assert lim.check("A", limit=2, window=100, global_limit=2) == 80  # global: 50+100-70; key: 0+100-70


def test_memory_is_bounded_by_key_cap():
    clk = FakeClock()
    lim = SlidingWindowLimiter(clock=clk, max_keys=100)
    for i in range(10_000):
        assert lim.check(f"k{i}", limit=5, window=3600, global_limit=0) is None
        clk.advance(0.001)
    assert lim.tracked_keys() <= 100
    # most recent keys are the ones retained
    assert "k9999" in lim._per_key and "k0" not in lim._per_key


def test_expired_keys_are_evicted_before_active_ones():
    clk = FakeClock()
    lim = SlidingWindowLimiter(clock=clk, max_keys=3)
    for k in ("old1", "old2"):
        lim.check(k, 5, 100, 0)
    clk.advance(200)  # old1/old2 expired
    lim.check("active", 5, 100, 0)
    lim.check("n1", 5, 100, 0)
    lim.check("n2", 5, 100, 0)  # cap reached -> expired keys dropped, active retained
    assert set(lim._per_key) == {"active", "n1", "n2"}


def test_per_key_and_global_timestamp_storage_is_bounded():
    clk = FakeClock()
    lim = SlidingWindowLimiter(clock=clk, max_keys=10)
    for _ in range(1000):
        lim.check("one", limit=20, window=3600, global_limit=50)
    assert len(lim._per_key["one"]) <= 20
    assert len(lim._global) <= 20  # blocked requests are never stored
    for i in range(1000):
        lim.check(f"k{i}", limit=20, window=3600, global_limit=50)
    assert len(lim._global) <= 50


def test_limiter_is_thread_safe():
    lim = SlidingWindowLimiter(clock=FakeClock())
    allowed = []

    def worker():
        for _ in range(50):
            if lim.check("same", limit=20, window=3600, global_limit=0) is None:
                allowed.append(1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(allowed) == 20


async def test_successful_response_shape_unchanged(limited, clock):
    async with make_client() as c:
        body = (await c.post(URL)).json()
    assert set(body) == {"access_token", "token_type", "user_id", "expires_at"}
