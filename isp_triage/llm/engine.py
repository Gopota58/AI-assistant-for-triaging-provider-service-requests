# -*- coding: utf-8 -*-
"""
llm/engine.py — LLM-обогащение (Вариант Б: LLM как точечный движок поверх ML).

Генерирует диагностику и пошаговую инструкцию для инженера. Используется
конвейером ТОЛЬКО для неуверенных случаев ML и/или «Выезд».

Реализован graceful fallback: если ollama не установлен/недоступен — функция
возвращает (None, None), и пайплайн откатывается на шаблонные инструкции.
Без LLM система полностью работает в режиме ML + правила.
"""
import re
import json
from typing import Tuple, Optional

from isp_triage.contract import Claim, ACTION_NAMES


PROMPT_TEMPLATE = """Ты — эксперт техподдержки интернет-провайдера. По заявке нужно дать
краткую диагностику и пошаговую инструкцию для инженера (на русском).

ЗАЯВКА: {text}

ПАРАМЕТРЫ СЕТИ:
- Линк: {link_status} (0-DOWN, 1-UP)
- Авторизация: {auth_status} (0-нет, 1-есть)
- Переподключений: {session_count}
- Затухание: {attenuation_db} dB
- PPPoE: {pppoe_status}, DHCP: {dhcp_status}, DNS: {dns_status}
- Ping до шлюза: {ping_gateway_ms} мс, до DNS: {ping_dns_ms} мс
- Ошибки CRC: {errors_crc}
- Wi-Fi RSSI: {wifi_rssi} dBm, PoE: {power_poe}
- Оборудование: {equipment_type} (наше: {equipment_owned}, гарантия: {warranty})
- Адрес: {address}

Предварительная классификация ML: {ml_action}.

Ответь СТРОГО в JSON:
{{"diagnosis": "короткая диагностика",
  "instructions": ["шаг 1", "шаг 2", "шаг 3"],
  "suggested_action": 0}}
где suggested_action: 0 — Дистанционно, 1 — Звонок, 2 — Выезд.
"""


def _build_prompt(claim: Claim, ml_action: int) -> str:
    return PROMPT_TEMPLATE.format(
        text=claim.text,
        link_status=claim.link_status, auth_status=claim.auth_status,
        session_count=claim.session_count, attenuation_db=claim.attenuation_db,
        pppoe_status=claim.pppoe_status, dhcp_status=claim.dhcp_status,
        dns_status=claim.dns_status, ping_gateway_ms=claim.ping_gateway_ms,
        ping_dns_ms=claim.ping_dns_ms, errors_crc=claim.errors_crc,
        wifi_rssi=claim.wifi_rssi, power_poe=claim.power_poe,
        equipment_type=claim.equipment_type, equipment_owned=claim.equipment_owned,
        warranty=claim.warranty, address=claim.address_str() or "—",
        ml_action=ACTION_NAMES.get(ml_action, str(ml_action)),
    )


def _parse(content: str) -> Tuple[Optional[str], Optional[list], Optional[int]]:
    """Извлекает JSON с diagnosis + instructions + suggested_action из ответа LLM."""
    try:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            return None, None, None
        data = json.loads(m.group())
        diag = data.get("diagnosis")
        inst = data.get("instructions")
        sugg = data.get("suggested_action")
        if isinstance(inst, str):
            inst = [inst]
        if sugg in (0, 1, 2):
            sugg = int(sugg)
        else:
            sugg = None
        if diag or inst:
            return diag, inst, sugg
    except Exception:
        pass
    return None, None, None


def enrich(claim: Claim, ml_action: int = 0) -> Tuple[Optional[str], Optional[list], Optional[int]]:
    """
    Возвращает (diagnosis, instructions, suggested_action).
    При недоступности ollama — (None, None, None).
    """
    prompt = _build_prompt(claim, ml_action)
    try:
        import ollama
        response = ollama.chat(
            model="llama3.2",
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1, "num_predict": 400},
        )
        content = response["message"]["content"]
        return _parse(content)
    except Exception:
        # ollama не установлен / недоступен — молча откатываемся.
        return None, None, None
