"""The DOJ holdout: addresses from US v. 4,340,000 Tether (N.D. Ohio 1:25-cv-00386) that must
never enter the label DB, so the DOJ match stays blind.

Source of truth is CK's data/doj/holdout.json (any shape: every 0x-address string in it counts,
and so does every truncated "prefix…suffix" string). The addresses from brief v3 §5 are built in
as a floor, so the guard works before that file exists.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from hound.chain.cache import REPO_ROOT

HOLDOUT_FILE = REPO_ROOT / "data" / "doj" / "holdout.json"

BRIEF_FULL = [
    "0xa1770ead287dc8e91631a7a323390d5b744f0021",  # A-7
    "0x4e5cda8f0d772ac57e947545192a0657ad47abb5",  # A-8
    "0xafd770d8898a0e323c607fe91358345e7b2378a5",  # A-9
    "0xcf9bbfa762ef5a84ba3d25350de941a6db485027",  # A-1
    "0x78366b2f6c5321ac30629c078120385ae2da1a06",
    "0x9eb0c71e79066552bdd05a69fc4dcac075db5e1f",
    "0xdf6fa72c71577c3a3209db202d4815021f0ed53f",
    "0x07fbb418aac62abc4ca3e7ee8ccf8ce7693e9d53",
    "0x58e99d9413bb6ce05748a84f76e5fff4bb2d0dcb",
]
BRIEF_TRUNCATED = ["e79…c2d6ad0", "a32…6f4dbb8", "212…4d9c794", "447…eb691", "d95…4be2cd4", "28b…fd1"]

_FULL = re.compile(r"0x[0-9a-fA-F]{40}")
_TRUNC = re.compile(r"(?:0x)?([0-9a-fA-F]{2,})\s*(?:…|\.\.\.+)\s*([0-9a-fA-F]{2,})")


class HoldoutViolation(RuntimeError):
    """A holdout address showed up somewhere it must not be (the label DB)."""


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v)


@lru_cache(maxsize=1)
def load(path: Path | None = None) -> tuple[frozenset[str], tuple[tuple[str, str], ...]]:
    """-> (full addresses, (prefix, suffix) pairs), lowercase, prefix without 0x."""
    full = {a.lower() for a in BRIEF_FULL}
    trunc = set()
    texts = list(BRIEF_TRUNCATED)
    p = path or HOLDOUT_FILE
    if p.exists():
        texts.extend(_strings(json.loads(p.read_text())))
    for s in texts:
        for m in _FULL.findall(s):
            full.add(m.lower())
        for pre, suf in _TRUNC.findall(_FULL.sub("", s)):
            trunc.add((pre.lower(), suf.lower()))
    return frozenset(full), tuple(sorted(trunc))


def matches(address: str) -> str | None:
    """The holdout entry `address` matches, or None. Ethereum-style addresses only."""
    a = address.lower()
    full, trunc = load()
    if a in full:
        return a
    body = a[2:] if a.startswith("0x") else a
    for pre, suf in trunc:
        if body.startswith(pre) and body.endswith(suf):
            return f"{pre}…{suf}"
    return None
