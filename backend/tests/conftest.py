import os

import pytest

LIVE = os.environ.get("HOUND_LIVE") == "1"


def pytest_collection_modifyitems(config, items):
    if LIVE:
        return
    skip = pytest.mark.skip(reason="live API test: set HOUND_LIVE=1")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _offline_chain(request, tmp_path, monkeypatch):
    """Unit tests never touch the network: a private empty cache, and hound.chain's fetchers
    replaced by the fixture chain (examples/ohnd_transfers.json). Labels stay real (local files).
    Live tests use the real adapters and warm the repo cache/."""
    from hound.chain import net
    net.reset_stats()
    if "live" in request.keywords:
        yield
        return
    monkeypatch.setenv("HOUND_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("HOUND_OFFLINE", raising=False)
    import hound.chain as chain
    from hound import fixture_chain as fc
    monkeypatch.setattr(chain, "get_transfers", fc.get_transfers)
    monkeypatch.setattr(chain, "freeze_status", lambda c, a, as_of=None: fc.freeze_status(c, a))
    monkeypatch.setattr(chain, "get_balance", fc.get_balance)
    from hound.watch import watchlist
    watchlist.reset()
    yield
