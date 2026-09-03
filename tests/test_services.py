# -*- coding: utf-8 -*-
"""Тесты периферии: топология, БЗ, экономика, фидбек, аудит, ML."""
import types

import pandas as pd
import pytest

from isp_triage import audit, feedback, impact, kb, topology
from isp_triage.contract import Claim
from isp_triage.triage import classifier as clf_mod


# ---------- топология ----------

def test_topology_is_deterministic():
    c = Claim(text="t", street="Ленина", building="5")
    a, b = topology.resolve(c), topology.resolve(c)
    assert a == b
    assert a["olt"].startswith("OLT-") and a["pon"].startswith("PON-")


def test_topology_cluster_detection():
    c = Claim(text="t", street="Мира", building="12")
    pon = topology.resolve(c)["pon"]
    assert topology.check_outage(c) is None
    for _ in range(topology.CLUSTER_THRESHOLD):
        topology.note_claim(pon)
    out = topology.check_outage(c)
    assert out and out["scope"] == "cluster"


def test_topology_active_alarm(monkeypatch):
    """Активный аларм NMS на PON: любая заявка узла — сразу авария."""
    c = Claim(text="нет интернета", street="Советская", building="40")
    pon = topology.resolve(c)["pon"]
    monkeypatch.setattr(topology, "ACTIVE_ALARMS",
                        {pon: {"type": "LOS", "olt": "OLT-9", "text": "LOS на узле"}})
    out = topology.check_outage(c)
    assert out and out["scope"] == "pon" and out["type"] == "LOS"


# ---------- база знаний ----------

def test_kb_retrieves_relevant_doc():
    c = Claim(text="ошибка 691 при авторизации pppoe")
    docs = kb.retrieve(c, action=0)
    assert docs and docs[0]["id"] == "REG-201"


def test_kb_ranks_relevant_doc_first():
    docs = kb.retrieve(Claim(text="собака перегрызла кабель"), action=2)
    assert docs and docs[0]["id"] == "REG-620"


def test_kb_respects_top_k():
    docs = kb.retrieve(Claim(text="абракадабра квантовая"), action=1, top_k=2)
    assert len(docs) <= 2


# ---------- экономика ----------

def _r(action, kind="subscriber"):
    return types.SimpleNamespace(action=action, final_kind=kind)


def test_impact_counts_and_savings():
    results = [_r(0)] * 6 + [_r(1)] * 2 + [_r(2)] + [_r(2, "outage")]
    s = impact.summarize(results, baseline_share=0.5)
    assert s["total"] == 10
    assert s["outage"] == 1
    assert s["no_dispatch"] == 9          # 6 + 2 + 1 аварийная
    assert s["saved_rolls"] == round(8 * 0.5) + 1
    assert s["saved_rub"] == s["saved_rolls"] * impact.TRUCK_ROLL_COST_RUB


def test_impact_empty():
    s = impact.summarize([])
    assert s["total"] == 0 and s["share_no_dispatch"] == 0.0


# ---------- human-in-the-loop ----------

def test_feedback_record_and_stats(tmp_path, monkeypatch):
    monkeypatch.setattr(feedback, "FEEDBACK_CSV", str(tmp_path / "fb.csv"))
    monkeypatch.setattr(feedback, "LABELED_CSV", str(tmp_path / "labeled.csv"))
    c = Claim(text="заявка", claim_id="42", street="Ленина", building="1")
    feedback.record(c, predicted=0, corrected=2, comment="поехали")
    st = feedback.stats()
    assert st["total"] == 1 and st["changed"] == 1
    assert st["agreement"] == 0.0
    lab = pd.read_csv(feedback.LABELED_CSV, encoding="utf-8-sig")
    assert int(lab.iloc[0]["true_action"]) == 2      # метку исправил человек
    assert lab.iloc[0]["street"] == "Ленина"         # признаки сохранены


# ---------- аудит ----------

def test_audit_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "AUDIT", str(tmp_path / "audit.log"))
    audit.log({"claim_id": "1", "action": "Выезд", "source": "hard_rule"})
    audit.log({"claim_id": "2", "action": "Дистанционно", "source": "ml"})
    entries = audit.recent(10)
    assert len(entries) == 2
    assert entries[0]["claim_id"] == "2"             # новые сверху


# ---------- ML ----------

def test_classifier_predict_bounds(trained_model):
    df = trained_model
    row = df.iloc[0]
    claim = Claim(**{k: v for k, v in row.items()
                     if k in Claim.__dataclass_fields__})
    action, conf, probs = clf_mod.predict(claim)
    assert action in (0, 1, 2)
    assert 0.0 <= conf <= 1.0
    assert abs(sum(probs) - 1.0) < 1e-6


def test_classifier_evaluate_metrics(trained_model):
    m = clf_mod.evaluate(trained_model)
    assert m is not None
    assert 0.8 < m["accuracy"] <= 1.0
    assert set(("Дистанционно", "Звонок", "Выезд")) <= set(m["report"].keys())
