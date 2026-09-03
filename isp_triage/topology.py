# -*- coding: utf-8 -*-
"""
topology.py — модель сети доступа и корреляция аварий (СИМУЛЯЦИЯ для L3).

Главный вопрос 3-й линии: это проблема ОДНОГО абонента или авария на узле
(OLT/PON/шкаф)? Здесь правдоподобная заглушка: адреса детерминированно
мапятся на OLT/PON/шкаф, есть поток активных аварий (как из NMS) и
кластеризация заявок по PON за короткое окно.

В бою: топология и алармы приходят из систем мониторинга (NMS/Alarm) и
пассивной сети (GPON: OLT → PON → сплиттер → ONT).
"""
import hashlib
from collections import defaultdict, deque
from typing import Optional

from isp_triage.contract import Claim

# Активные аварии (симуляция потока алармов из NMS). Ключ — id сущности.
ACTIVE_ALARMS = {
    "PON-14": {"type": "LOS", "olt": "OLT-2",
               "text": "Optical loss (LOS) на PON-14 — нет оптического сигнала"},
    "OLT-5": {"type": "POWER", "olt": "OLT-5",
              "text": "Пропало питание OLT-5 — затронуты все PON узла"},
}

PON_COUNT = 20
OLT_COUNT = 6
CLUSTER_THRESHOLD = 5          # сколько заявок на одном PON = «похоже на аварию»

# Скользящее окно последних заявок по PON (для кластеризации).
_window = defaultdict(lambda: deque(maxlen=100))


def _h(s: str) -> int:
    return int(hashlib.md5(s.encode("utf-8")).hexdigest(), 16)


def resolve(claim: Claim) -> dict:
    """Привязывает адрес заявки к узлу сети (детерминированно)."""
    key = f"{claim.street} {claim.building}"
    olt = f"OLT-{(_h(key) % OLT_COUNT) + 1}"
    pon = f"PON-{(_h(key) % PON_COUNT) + 1}"
    cabinet = f"Шкаф-{(_h(key) % 40) + 1}"
    return {"olt": olt, "pon": pon, "cabinet": cabinet, "address": claim.address_str()}


def note_claim(pon: str):
    _window[pon].append(1)


def reset_window():
    _window.clear()


def check_outage(claim: Claim) -> Optional[dict]:
    """
    Возвращает описание аварии, если заявка попадает на аварийный узел
    или рядом кластеризуются заявки на том же PON. Иначе None.
    """
    topo = resolve(claim)
    pon, olt = topo["pon"], topo["olt"]

    if pon in ACTIVE_ALARMS:
        a = ACTIVE_ALARMS[pon]
        return {"scope": "pon", "id": pon, "olt": a["olt"], "type": a["type"],
                "text": a["text"], "affected": max(len(_window[pon]), 1)}

    if olt in ACTIVE_ALARMS:
        a = ACTIVE_ALARMS[olt]
        return {"scope": "olt", "id": olt, "olt": olt, "type": a["type"],
                "text": a["text"], "affected": "все PON узла"}

    if len(_window[pon]) >= CLUSTER_THRESHOLD:
        return {"scope": "cluster", "id": pon, "olt": olt, "type": "CLUSTER",
                "text": f"Скопление заявок на {pon} за короткое время",
                "affected": len(_window[pon])}

    return None
