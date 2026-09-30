"""Unit tests: knowledge loader + BM25 retrieval + hypothesis ranking (§11, §19)."""
from knowledge.loader import KnowledgeBase, evidence_tags_for_value
from ai.embeddings.bm25 import BM25Index, build_knowledge_index, tokenize
from diagnostics.rules.hypotheses import rank_hypotheses, evidence_tags_from_observations


def kb() -> KnowledgeBase:
    return KnowledgeBase()


def test_all_three_devices_load():
    k = kb()
    assert not k.load_errors, k.load_errors
    assert set(k.devices) >= {"router_home", "printer_office", "monitor_display"}


def test_router_structure_complete():
    dev = kb().get("router_home")
    assert dev is not None
    assert dev.indicators and dev.symptoms and dev.hypotheses
    assert dev.blocked_actions
    assert dev.escalation_conditions
    assert dev.resolution_criteria
    for hyp in dev.hypotheses:
        action = hyp["action"]
        assert action["text"]
        assert "expected_visual_change" in action
        assert action["expected_visual_change"]["indicator"]


def test_symptom_matching():
    k = kb()
    dev = k.get("router_home")
    sym = k.match_symptom(dev, "my wifi is not connecting to the internet")
    assert sym is not None and sym["id"] == "no_network"
    sym2 = k.match_symptom(dev, "the router is completely dead, no lights")
    assert sym2 is not None and sym2["id"] == "no_power"


def test_evidence_tags():
    assert "led_amber_solid" in evidence_tags_for_value("amber_solid")
    assert "led_not_green" in evidence_tags_for_value("amber_solid")
    assert "led_unknown" in evidence_tags_for_value("unknown")


def test_rank_hypotheses_orders_by_confidence_and_filters():
    k = kb()
    dev = k.get("router_home")
    evidence = {"led_amber_solid", "led_not_green"}
    hyps = rank_hypotheses(dev, "no_network", evidence)
    assert hyps, "expected hypotheses for amber LED + no_network"
    confs = [h.confidence for h in hyps]
    assert confs == sorted(confs, reverse=True)
    # wan_cable_loose excludes green; green evidence must remove it
    ev_green = {"led_green_solid"}
    hyps_green = rank_hypotheses(dev, "no_network", ev_green)
    assert all(h.id != "wan_cable_loose" for h in hyps_green)


def test_evidence_requires_any_gate():
    k = kb()
    dev = k.get("router_home")
    # modem_down requires amber_solid|red_solid
    hyps = rank_hypotheses(dev, "no_network", {"led_unknown", "led_not_green"})
    ids = {h.id for h in hyps}
    assert "modem_down" not in ids


def test_observations_to_evidence_tags():
    k = kb()
    dev = k.get("router_home")
    tags = evidence_tags_from_observations({"status_led": "amber_solid"}, dev)
    assert "led_amber_solid" in tags
    # unknown indicator value must not crash and maps to unknown tags
    tags2 = evidence_tags_from_observations({"status_led": "weird_value"}, dev)
    assert "led_unknown" in tags2


def test_bm25_tokenize():
    toks = tokenize("Wi-Fi isn't working!")
    assert "working" in toks
    assert "the" not in tokenize("the router is dead")


def test_bm25_search_finds_relevant_docs():
    idx = BM25Index([
        ("a", "router has amber light and no internet"),
        ("b", "printer paper jam error"),
        ("c", "monitor no signal input"),
    ])
    res = idx.search("amber light no internet")
    assert res and res[0].doc_id == "a"


def test_knowledge_index_search_actionable():
    k = kb()
    idx = build_knowledge_index(k.all_devices())
    res = idx.search("wifi not connecting internet cable")
    assert res, "expected retrieval hits"
    assert any("router" in r.doc_id for r in res)


def test_knowledge_loader_reports_missing_dir(tmp_path):
    from knowledge.loader import KnowledgeBase as KB
    broken = KB(devices_dir=tmp_path / "nope")
    assert broken.load_errors
    assert not broken.devices
