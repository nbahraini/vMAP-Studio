import pytest

from vmap.core.model import ROOT, Topic
from vmap.core.search import (SearchError, SearchOptions, compile_pattern, find_topics,
                              replace_text)


@pytest.fixture
def tree():
    root = Topic("Network Security", type=ROOT)
    fw = Topic("Firewall rules", notes="iptables and nftables")
    vpn, seg = Topic("VPN"), Topic("network segmentation")
    root.add_child(fw)
    root.add_child(vpn)
    fw.add_child(seg)
    return root


def titles(topics):
    return [t.title for t in topics]


def test_case_handling(tree):
    assert titles(find_topics(tree, SearchOptions("network"))) == ["Network Security",
                                                                  "network segmentation"]
    assert titles(find_topics(tree, SearchOptions("network", case_sensitive=True))) == [
        "network segmentation"]


def test_whole_word_notes_and_regex(tree):
    assert find_topics(tree, SearchOptions("net", whole_word=True)) == []
    assert titles(find_topics(tree, SearchOptions("VPN", whole_word=True))) == ["VPN"]
    assert find_topics(tree, SearchOptions("nftables")) == []
    assert titles(find_topics(tree, SearchOptions("nftables", include_notes=True))) == [
        "Firewall rules"]
    assert titles(find_topics(tree, SearchOptions(r"^(VPN|Firewall)", regex=True))) == [
        "Firewall rules", "VPN"]


def test_persian_whole_word():
    root = Topic("شبکه امن", type=ROOT)
    assert titles(find_topics(root, SearchOptions("شبکه", whole_word=True))) == ["شبکه امن"]


@pytest.mark.parametrize("options", [SearchOptions(""), SearchOptions("(", regex=True),
                                     SearchOptions("x" * 1001)])
def test_invalid_patterns(options):
    with pytest.raises(SearchError):
        compile_pattern(options)


def test_replacement_modes():
    plain = compile_pattern(SearchOptions("a.b"))
    assert replace_text("a.b axb", plain, r"\1") == (r"\1 axb", 1)     # literal, no escapes
    rx = compile_pattern(SearchOptions(r"(\w+)@(\w+)", regex=True))
    assert replace_text("user@host", rx, r"\2:\1", regex=True) == ("host:user", 1)
    with pytest.raises(SearchError):
        replace_text("x", compile_pattern(SearchOptions("x", regex=True)), r"\3", regex=True)
