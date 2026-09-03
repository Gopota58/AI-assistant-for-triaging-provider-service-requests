# -*- coding: utf-8 -*-
"""
impact.py — оценка экономического эффекта от фильтрации заявок (ДЕМО-допущения).

Цифры условные, чтобы показать заказчику ПОРЯДОК выгоды. В боевой системе
стоимость/время выезда берутся из нормативов компании и данных Helpdesk/WOS.
"""
from typing import List

# Условные допущения для оценки.
TRUCK_ROLL_COST_RUB = 2000   # средняя стоимость одного выезда (ГСМ, амортизация, ФОТ)
TRUCK_ROLL_HOURS = 2.0       # средние затраты времени инженера на выезд с дорогой


def summarize(results, baseline_share: float = 0.4) -> dict:
    """
    results — список Result из pipeline.
    baseline_share — доля абонентских заявок без выезда, которые БЕЗ ассистента
    ушли бы на выезд (консервативное допущение; по умолчанию 40%).

    Заявки, схлопнутые в сетевой инцидент по аварии (final_kind='outage'),
    считаются как «без индивидуального выезда» — в этом и смысл корреляции:
    один выезд узловой бригады вместо N выездов к абонентам.
    """
    total = len(results)
    by_action = {0: 0, 1: 0, 2: 0}
    outage = 0
    for r in results:
        if getattr(r, "final_kind", "subscriber") == "outage":
            outage += 1
        else:
            by_action[r.action] = by_action.get(r.action, 0) + 1

    subscriber_no_dispatch = by_action[0] + by_action[1]
    no_dispatch = subscriber_no_dispatch + outage
    share_no_dispatch = (no_dispatch / total) if total else 0.0

    # Потенциально предотвращённые выезды: абонентские (с допущением) + все аварийные.
    saved_rolls = round(subscriber_no_dispatch * baseline_share) + outage
    saved_rub = saved_rolls * TRUCK_ROLL_COST_RUB
    saved_hours = saved_rolls * TRUCK_ROLL_HOURS

    return {
        "total": total,
        "by_action": by_action,
        "outage": outage,
        "no_dispatch": no_dispatch,
        "share_no_dispatch": share_no_dispatch,
        "baseline_share": baseline_share,
        "saved_rolls": saved_rolls,
        "saved_rub": saved_rub,
        "saved_hours": saved_hours,
    }
