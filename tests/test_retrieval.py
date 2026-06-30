"""Vault keyword retrieval: indexing, search, query sanitisation, freshness."""
from __future__ import annotations

from agent import retrieval


def _seed(sandbox):
    (sandbox / "vault" / "03-resources" / "espresso.md").write_text(
        "# Espresso\nThe Gaggia Classic Pro is a solid home machine."
    )
    (sandbox / "vault" / "03-resources" / "running.md").write_text(
        "# Running\nZone 2 training builds an aerobic base."
    )


def test_reindex_and_search(sandbox):
    _seed(sandbox)
    retrieval.init_db()
    n = retrieval.reindex_vault()
    assert n == 2
    hits = retrieval.search_vault("gaggia espresso")
    assert hits and hits[0]["path"].endswith("espresso.md")
    assert "«" in hits[0]["snippet"]  # snippet markers present


def test_search_is_safe_on_hostile_input(sandbox):
    _seed(sandbox)
    retrieval.init_db()
    retrieval.reindex_vault()
    assert retrieval.search_vault('"); DROP * AND ((') == []
    assert retrieval.search_vault("   ") == []


def test_index_and_remove_file_keep_search_fresh(sandbox):
    retrieval.init_db()
    f = sandbox / "vault" / "00-inbox" / "note.md"
    f.write_text("# Kdb\nNote about kdb+ and time series.")
    retrieval.index_file("vault/00-inbox/note.md")
    assert any(h["path"].endswith("note.md") for h in retrieval.search_vault("kdb"))
    retrieval.remove_file("vault/00-inbox/note.md")
    assert retrieval.search_vault("kdb") == []
