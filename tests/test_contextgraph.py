"""Context graph: pure bounds-expansion logic + (optional) live symgraph smoke."""
from __future__ import annotations

import shutil

import pytest

from sembl_stack.contextgraph import (FileGraph, SymgraphGraph, expand_bounds,
                                       expand_paths)


def _graph() -> FileGraph:
    # a.py -> b.py -> c.py ; d.py is isolated
    return FileGraph(
        nodes=["a.py", "b.py", "c.py", "d.py"],
        edges=[
            {"from": "a.py", "to": "b.py", "strength": 3},
            {"from": "b.py", "to": "c.py", "strength": 1},
        ],
    )


# the logic tests disable the closure cap (max_fraction=1.0); the cap has its own test.
def test_expand_one_hop_both_directions():
    # from b: reaches a (caller) and c (callee) at one hop
    assert expand_paths(["b.py"], _graph(), hops=1, max_fraction=1.0) == ["a.py", "b.py", "c.py"]


def test_expand_two_hops_transitive():
    # from a: 1 hop -> b, 2 hops -> c
    assert expand_paths(["a.py"], _graph(), hops=2, max_fraction=1.0) == ["a.py", "b.py", "c.py"]
    assert expand_paths(["a.py"], _graph(), hops=1, max_fraction=1.0) == ["a.py", "b.py"]


def test_seed_always_included_and_strength_filter():
    # d has no edges -> only itself
    assert expand_paths(["d.py"], _graph(), hops=2, max_fraction=1.0) == ["d.py"]
    # min_strength prunes the weak b->c edge
    assert expand_paths(["a.py"], _graph(), hops=5, min_strength=2, max_fraction=1.0) == ["a.py", "b.py"]


def test_slash_normalization():
    g = FileGraph(nodes=["src/x.py", "src/y.py"],
                  edges=[{"from": "src\\x.py", "to": "src\\y.py", "strength": 1}])
    assert expand_paths(["src\\x.py"], g, hops=1, max_fraction=1.0) == ["src/x.py", "src/y.py"]


def test_closure_cap_abandons_when_too_dense():
    # 5 nodes; 1 hop from a reaches b,c -> closure 3/5 = 60%.
    g = FileGraph(
        nodes=["a.py", "b.py", "c.py", "d.py", "e.py"],
        edges=[{"from": "a.py", "to": x, "strength": 5} for x in ("b.py", "c.py")],
    )
    # 60% > 40% cap -> abandon, return bare seed
    assert expand_paths(["a.py"], g, hops=1, max_fraction=0.4) == ["a.py"]
    # 60% < 90% cap -> expansion kept
    assert expand_paths(["a.py"], g, hops=1, max_fraction=0.9) == ["a.py", "b.py", "c.py"]


def test_expand_bounds_dir_seed_keeps_originals():
    # editable dir "src/app/" seeds the indexed files under it, grows one hop, and the
    # original directory entry is preserved.
    g = FileGraph(
        nodes=["src/app/core.py", "src/app/util.py", "src/lib/dep.py", "infra/x.py"],
        edges=[{"from": "src/app/core.py", "to": "src/lib/dep.py", "strength": 4}],
    )
    out = expand_bounds(["src/app/"], g, hops=1, max_fraction=1.0)
    assert "src/app/" in out                 # original directory entry kept
    assert "src/lib/dep.py" in out           # coupled sibling recovered
    assert "infra/x.py" not in out           # unrelated file untouched


def test_expand_bounds_no_indexed_seed_is_noop():
    g = FileGraph(nodes=["a.py"], edges=[])
    assert expand_bounds(["does/not/exist/"], g) == ["does/not/exist/"]


@pytest.mark.skipif(not shutil.which("symgraph"), reason="symgraph not installed")
def test_symgraph_available():
    assert SymgraphGraph().available()
