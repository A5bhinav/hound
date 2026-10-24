import os

import pytest

os.environ.setdefault("HOUND_NO_DOTENV", "1")  # tests never read the real .env keys
os.environ.setdefault("HOUND_NO_PREWARM", "1")
# intake state goes to a throwaway file, never the repo's cache/
import tempfile  # noqa: E402

os.environ.setdefault("HOUND_STATE_FILE", os.path.join(tempfile.mkdtemp(prefix="hound-test-"), "intake_state.json"))  # no background replay trace outliving a test's patches

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
    monkeypatch.setattr(chain, "freeze_status", lambda c, a, as_of=None, **k: fc.freeze_status(c, a))
    monkeypatch.setattr(chain, "get_balance", fc.get_balance)
    monkeypatch.setattr(chain, "get_native_txs", fc.get_native_txs, raising=False)
    monkeypatch.setattr(chain, "is_contract", lambda c, a: False)
    from hound.chain import labels
    real_label = labels.label
    monkeypatch.setattr(labels, "label", lambda c, a, network=True: real_label(c, a, network=False))
    from hound.watch import watchlist
    watchlist.reset()
    yield
