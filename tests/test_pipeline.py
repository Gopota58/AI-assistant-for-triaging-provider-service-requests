# -*- coding: utf-8 -*-
"""Тесты конвейера: приоритет правил, гейтинг, корреляция аварий, наряды."""
import pytest

from isp_triage import audit, topology
from isp_triage.contract import Claim
from isp_triage.connectors.workorders import WorkOrderConnector
from isp_triage import pipeline
from isp_triage.pipeline import process, ESCALATE_THRESHOLD


@pytest.fixture(autouse=True)
def _clean_side_effects(tmp_path, monkeypatch):
    """Аудит — в tmp, окно топологии и алармы NMS — чисты (детерминизм)."""
    monkeypatch.setattr(audit, "AUDIT", str(tmp_path / "audit.log"))
    monkeypatch.setattr(topology, "ACTIVE_ALARMS", {})
    topology.reset_window()
    yield
    topology.reset_window()


@pytest.fixture
def no_llm(monkeypatch):
    """Гарантируем детерминизм: LLM-ветка недоступна (как без ollama)."""
    monkeypatch.setattr(pipeline, "llm_enrich", lambda *a, **k: (None, None, None))


def test_hard_rule_beats_ml(trained_model, no_llm):
    """Порт DOWN — правило обязано перебить ML и дать «Выезд»."""
    monkey_action = 0  # пусть даже ML скажет «Дистанционно»
    claim = Claim(text="пропал интернет", link_status=0, auth_status=0,
                  street="Ленина", building="1")
    res = process(claim, WorkOrderConnector())
    assert res.action == 2
    assert res.source == "hard_rule"
    assert res.confidence == 1.0
    assert res.rules_flag == (res.ml_action != 2)
    assert not res.escalate  # жёсткое правило не эскалируется


def test_work_order_created(trained_model, no_llm):
    claim = Claim(text="не работает dns", dns_status=0, street="Мира", building="7")
    res = process(claim, WorkOrderConnector())
    assert res.wo_ref is not None
    assert res.wo_ref["order_id"].startswith("WO-")


def test_gating_escalates_low_confidence(trained_model, monkeypatch, no_llm):
    """Низкая уверенность ML → эскалация сеньору (гейтинг)."""
    monkeypatch.setattr(pipeline, "ml_predict", lambda c: (1, 0.5, None))
    claim = Claim(text="что-то непонятное", street="Кирова", building="2")
    res = process(claim)
    assert res.source in ("fallback", "llm")
    assert res.confidence < ESCALATE_THRESHOLD
    assert res.escalate


def test_high_confidence_no_escalation(trained_model, monkeypatch, no_llm):
    monkeypatch.setattr(pipeline, "ml_predict", lambda c: (0, 0.95, None))
    claim = Claim(text="настройте dns", dns_status=0, street="Кирова", building="2")
    res = process(claim)
    assert res.source == "ml"
    assert not res.escalate


def test_outage_correlation_clusters_claims(trained_model, monkeypatch, no_llm):
    """Скопление заявок на одном PON → сетевой инцидент, а не выезд."""
    monkeypatch.setattr(pipeline, "ml_predict", lambda c: (2, 0.9, None))
    claim = Claim(text="район без интернета", street="Пушкина", building="9")
    pon = topology.resolve(claim)["pon"]
    for _ in range(topology.CLUSTER_THRESHOLD):
        topology.note_claim(pon)

    res = process(claim, WorkOrderConnector())
    assert res.final_kind == "outage"
    assert res.source == "correlation"
    assert res.escalate
    assert res.wo_ref["order_id"].startswith("INC-")
    assert any("узлов" in s.lower() for s in res.instructions)


def test_result_has_references_and_trace(trained_model, no_llm):
    claim = Claim(text="ошибка 691, не могу войти", pppoe_status=0,
                  street="Гагарина", building="3")
    res = process(claim)
    assert res.trace and res.trace[0]["stage"] in ("correlation", "ml_triage")
    assert isinstance(res.references, list)
    assert res.instructions  # план работ обязан быть
