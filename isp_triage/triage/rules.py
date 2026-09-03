# -*- coding: utf-8 -*-
"""
triage/rules.py — жёсткие правила-валидатор (физика сети).

Эти правила описывают ОДНОЗНАЧНЫЕ физические неисправности, которые ML
может не заметить или перепутать. В конвейере (pipeline.py) они имеют
ВЫСШИЙ приоритет безопасности: если правило срабатывает — действие «Выезд».
"""
from typing import Tuple, Optional

from isp_triage.contract import Claim


def validate(claim: Claim) -> Tuple[Optional[int], Optional[str]]:
    """
    Возвращает (action, reason) если сработало жёсткое правило,
    либо (None, None) если правило молчит.
    """
    text = claim.text.lower()

    if claim.link_status == 0 and claim.auth_status == 0:
        return 2, "Жёсткое правило: линк и авторизация отсутствуют (полный обрыв)."

    if claim.link_status == 0:
        return 2, "Жёсткое правило: порт коммутатора DOWN (нет линка)."

    if claim.attenuation_db >= 40 and claim.link_status == 1:
        return 2, f"Жёсткое правило: критическое затухание {claim.attenuation_db} dB."

    if claim.errors_crc > 50:
        return 2, f"Жёсткое правило: множественные ошибки CRC ({claim.errors_crc})."

    if claim.equipment_owned == 0 and ("не наше" in text or "чужое" in text):
        return 2, "Жёсткое правило: оборудование не наше, требуется выезд."

    if ("собака" in text or "грызла" in text or "перегрызла" in text) and "кабель" in text:
        return 2, "Жёсткое правило: кабель повреждён животными."

    return None, None
