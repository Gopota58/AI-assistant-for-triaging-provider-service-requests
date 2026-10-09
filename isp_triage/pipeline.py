# -*- coding: utf-8 -*-
"""
pipeline.py — оркестратор конвейера (Вариант Б, уровень L3).

Порядок обработки заявки:
  0. Корреляция с авариями/топологией (L3-первый вопрос: один абонент или узел?)
  1. ML-триаж (быстро, детерминированно, измеримо)
  2. Жёсткие правила-валидатор (физика, ВЫСШИЙ приоритет безопасности)
  3. LLM-обогащение (точечно: низкая уверенность ML или «Выезд»)
  4. RAG по базе знаний (ссылки на регламенты)
  5. Гейтинг по уверенности (эскалация сеньору)
  6. WOS (Work Order System) — наряд абонентский или сетевой инцидент
  7. Аудит решения

Result несёт финальное решение и все компоненты (ML/правила/LLM/авария/ссылки),
чтобы UI показывал «как и почему» без дублирования логики.
"""
from dataclasses import dataclass, field
from typing import Optional, List

from isp_triage.contract import Claim, ACTION_NAMES
from isp_triage.triage.classifier import predict as ml_predict
from isp_triage.triage import rules as rules_mod
from isp_triage.llm.engine import enrich as llm_enrich
from isp_triage.connectors.workorders import WorkOrderConnector
from isp_triage import topology, kb, audit

CONFIDENCE_THRESHOLD = 0.7
ESCALATE_THRESHOLD = 0.85


@dataclass
class Result:
    claim_id: Optional[str]
    action: int
    action_name: str
    source: str                 # correlation | ml | hard_rule | llm | fallback
    confidence: float
    final_kind: str = "subscriber"   # subscriber | outage

    # Компоненты решения (для UI «мнений» и трассы)
    ml_action: int = 0
    ml_confidence: float = 0.0
    rules_action: Optional[int] = None
    rules_reason: Optional[str] = None
    llm_action: Optional[int] = None
    llm_diagnosis: Optional[str] = None
    llm_instructions: Optional[list] = None

    diagnosis: Optional[str] = None
    instructions: List[str] = field(default_factory=list)
    references: List[dict] = field(default_factory=list)
    outage: Optional[dict] = None
    topo: Optional[dict] = None
    escalate: bool = False
    wo_ref: Optional[dict] = None
    trace: List[dict] = field(default_factory=list)
    rules_flag: bool = False


def _fault_distance_m(claim: Claim) -> float:
    """Грубая оценка расстояния до предполагаемого обрыва (модель ~0.35 dB/м)."""
    if claim.attenuation_db <= 0:
        return 0.0
    est = claim.attenuation_db / 0.35
    return round(min(est, max(claim.cable_length_m, 1.0)), 1)


def _diagnose(claim: Claim, action: int) -> str:
    """Конкретный диагноз из параметров сети: что и почему."""
    findings = []
    if claim.link_status == 0:
        findings.append("линк на порту DOWN")
    if claim.auth_status == 0:
        findings.append("авторизация не проходит")
    if claim.attenuation_db >= 25:
        findings.append(f"затухание {claim.attenuation_db} dB (норма ≤25)")
    if claim.errors_crc > 20:
        findings.append(f"множественные ошибки CRC ({claim.errors_crc})")
    if claim.power_poe == 0:
        findings.append("отсутствует PoE-питание")
    if claim.equipment_owned == 0:
        findings.append("оборудование не наше")
    if "собака" in claim.text.lower() or "грызла" in claim.text.lower() or "перегрызла" in claim.text.lower():
        findings.append("кабель повреждён животными")
    if not findings:
        findings.append("явных физических дефектов не обнаружено")
    addr = claim.address_str() or "адрес не указан"
    return (f"Диагноз по адресу {addr}: {', '.join(findings)}. "
            f"Классификация — «{ACTION_NAMES[action]}».")


def _instructions_for(claim: Claim, action: int) -> List[str]:
    """Конкретный план действий инженера (fallback, когда LLM недоступен)."""
    s: List[str] = []
    addr = claim.address_str() or "адрес не указан"
    entrance = claim.entrance or "?"
    floor = claim.floor or "?"

    if action == 0:  # Дистанционно
        s.append(f"📡 Удалённо, без выезда. Абонент: {addr}.")
        if claim.link_status == 0:
            s.append("Включить порт на коммутаторе (проверить блокировку антифродом).")
        if claim.pppoe_status == 0:
            s.append("Сбросить PPPoE-сессию на порту доступа, проверить логин/пароль (ошибки 691/769).")
        if claim.dhcp_status == 0:
            s.append("Обновить DHCP-аренду (release/renew) на порту.")
        if claim.dns_status == 0:
            s.append("Прописать DNS 8.8.8.8 / 1.1.1.1 на роутере абонента.")
        if claim.vlan_id != 100:
            s.append("Сменить VLAN на 100 на порту доступа.")
        if len(s) == 1:
            s.append("Удалённо перезагрузить оборудование абонента, проверить статус в WOS (линк/авторизация/затухание).")
        s.append("Проконтролировать результат в WOS и закрыть заявку.")

    elif action == 1:  # Звонок
        s.append(f"📞 Позвонить абоненту ({addr}), уточнить детали.")
        if claim.pppoe_status == 0 and claim.dhcp_status == 1:
            s.append("Уточнить логин и пароль PPPoE, проверить на ошибки авторизации.")
        if claim.dns_status == 0:
            s.append("Попросить проверить настройки DNS на роутере.")
        if claim.ping_gateway_ms > 100:
            s.append("Спросить, не запущена ли фоновая загрузка, влияющая на скорость.")
        if "файрвол" in claim.text.lower():
            s.append("Попросить отключить файрвол и повторить проверку доступа.")
        if "wi-fi" in claim.text.lower() or "wifi" in claim.text.lower():
            s.append("Уточнить расстояние до роутера и номер Wi-Fi канала.")
        s.append("Если удалённо не решается — назначить выезд (см. план выезда).")

    else:  # Выезд
        s.append(f"🚚 Выезд по адресу: {addr}.")
        s.append(f"Маршрут: подъезд №{entrance}, этаж {floor}, квартира — уточнить у абонента.")
        s.append(f"Точка входа кабеля — патч-панель/кросс в подъезде №{entrance} (техэтаж или 1 этаж).")
        if claim.link_status == 0 or claim.attenuation_db >= 25 or claim.errors_crc > 20:
            dist = _fault_distance_m(claim)
            ratio = (dist / claim.cable_length_m) if claim.cable_length_m else 1.0
            approx_floor = max(1, round(ratio * (claim.floor or 1))) if claim.floor else "?"
            s.append("Проверить физическое подключение на патч-панели: пара подключена? "
                     "Переобжать коннектор (RJ-45) при повреждении.")
            s.append(f"По затуханию {claim.attenuation_db} dB / CRC {claim.errors_crc}: обрыв "
                     f"предположительно в ~{dist} м от коммутатора (ориентир — этаж {approx_floor}). "
                     f"Заменить участок кабеля или коннектор.")
        if "собака" in claim.text.lower() or "грызла" in claim.text.lower() or "перегрызла" in claim.text.lower():
            s.append("Кабель повреждён животными — заменить участок от точки входа до квартиры, установить защиту.")
        if claim.power_poe == 0:
            s.append("Нет PoE-питания — проверить коммутатор/инжектор в подъезде, заменить блок питания.")
        if claim.equipment_owned == 0:
            s.append("Оборудование не наше — оформить платное подключение, взять роутер на продажу/аренду.")
        if claim.equipment_type in ("роутер", "приставка", "ONT", "медиаконвертер", "коммутатор"):
            if claim.warranty == 1:
                s.append(f"Заменить {claim.equipment_type} по гарантии.")
            else:
                s.append(f"Заменить {claim.equipment_type} (вне гарантии — за счёт абонента).")
        s.append("После работ: измерить затухание, убедиться в появлении линка и авторизации, оформить наряд в WOS.")

    return s


def _outage_instructions(outage: dict) -> List[str]:
    return [
        f"🚨 {outage['text']} (объект: {outage.get('olt','')} / {outage['id']}).",
        f"Затронуто абонентов/заявок: {outage['affected']}. Объединить заявки по этому узлу в один инцидент.",
        "Эскалировать на узловую бригаду — НЕ направлять выездного к одному абоненту.",
        "Абонентам — автоуведомление об известной аварии и ориентировочном сроке восстановления.",
    ]


def process(claim: Claim, wos: Optional[WorkOrderConnector] = None) -> Result:
    trace: List[dict] = []

    # 0. Корреляция с авариями/топологией (L3-первый вопрос)
    topo = topology.resolve(claim)
    topology.note_claim(topo["pon"])
    outage = topology.check_outage(claim)
    if outage:
        refs = kb.retrieve(claim, 2)
        instr = _outage_instructions(outage)
        wo_ref = wos.create_incident(claim, outage) if wos else None
        trace.append({"stage": "correlation", "detail": outage["text"], "id": outage["id"]})
        audit.log({"claim_id": claim.claim_id, "action": "Авария на узле",
                   "source": "correlation", "node": outage["id"], "escalated": True})
        return Result(
            claim_id=claim.claim_id, action=2, action_name="Авария на узле",
            source="correlation", confidence=1.0, final_kind="outage",
            ml_action=2, ml_confidence=0.0,
            diagnosis=f"🚨 {outage['text']} — узел {outage.get('olt','')} / {outage['id']}.",
            instructions=instr, references=refs, outage=outage, topo=topo,
            escalate=True, wo_ref=wo_ref, trace=trace,
        )

    # 1. ML-триаж
    action_ml, conf, _ = ml_predict(claim)
    trace.append({"stage": "ml_triage", "action": action_ml,
                  "action_name": ACTION_NAMES[action_ml], "confidence": round(conf, 3)})

    # 2. Жёсткие правила (физика) — высший приоритет
    r_action, r_reason = rules_mod.validate(claim)

    # 3. LLM-обогащение (вызываем один раз, сохраняем компоненты)
    llm_diag, llm_inst, llm_action = (None, None, None)
    if conf < CONFIDENCE_THRESHOLD or action_ml == 2:
        llm_diag, llm_inst, llm_action = llm_enrich(claim, action_ml)
        if llm_diag:
            trace.append({"stage": "llm", "detail": "LLM сгенерировал диагностику/инструкцию"})

    # Принятие решения
    if r_action is not None:
        action = r_action
        source = "hard_rule"
        confidence = 1.0
        rules_flag = (r_action != action_ml)
        trace.append({"stage": "hard_rule", "action": action,
                      "detail": r_reason, "ml_disagreed": rules_flag})
    else:
        rules_flag = False
        if conf >= CONFIDENCE_THRESHOLD:
            action, source, confidence = action_ml, "ml", conf
        else:
            if llm_diag:
                action, source, confidence = action_ml, "llm", conf
            else:
                action, source, confidence = action_ml, "fallback", conf
                trace.append({"stage": "fallback", "detail": "LLM недоступен, решение за ML"})

    # Диагностика и инструкции
    diagnosis: Optional[str] = None
    instructions: List[str] = []
    if source == "llm" and llm_diag:
        diagnosis = llm_diag
        instructions = llm_inst if isinstance(llm_inst, list) else [llm_inst] if llm_inst else []
    if not instructions:
        instructions = _instructions_for(claim, action)
    if diagnosis is None:
        diagnosis = r_reason if source == "hard_rule" else _diagnose(claim, action)

    # 4. RAG по базе знаний
    references = kb.retrieve(claim, action)
    if references:
        trace.append({"stage": "kb", "detail": f"подобрано документов: {len(references)}"})

    # 5. Гейтинг по уверенности → эскалация сеньору
    escalate = (source != "hard_rule") and (confidence < ESCALATE_THRESHOLD)
    if escalate:
        trace.append({"stage": "gating", "detail": f"уверенность {confidence:.2f} < {ESCALATE_THRESHOLD} → эскалация сеньору"})

    # 6. WOS — абонентский наряд
    wo_ref = None
    if wos is not None:
        wo_ref = wos.create_work_order(claim, action)
        trace.append({"stage": "wos", "order": wo_ref.get("order_id")})

    # 7. Аудит
    audit.log({"claim_id": claim.claim_id, "action": ACTION_NAMES[action],
               "source": source, "confidence": round(confidence, 3),
               "pon": topo["pon"], "escalated": escalate})

    return Result(
        claim_id=claim.claim_id, action=action, action_name=ACTION_NAMES[action],
        source=source, confidence=confidence, final_kind="subscriber",
        ml_action=action_ml, ml_confidence=conf,
        rules_action=r_action, rules_reason=r_reason,
        llm_action=llm_action, llm_diagnosis=llm_diag, llm_instructions=llm_inst,
        diagnosis=diagnosis, instructions=instructions, references=references,
        outage=None, topo=topo, escalate=escalate, wo_ref=wo_ref,
        trace=trace, rules_flag=rules_flag,
    )
