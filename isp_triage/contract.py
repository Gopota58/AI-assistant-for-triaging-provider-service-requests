# -*- coding: utf-8 -*-
"""
contract.py — ЕДИНЫЙ контракт данных заявки (Вариант Б).

Это суперсет прежних (легаси) схем:
  * «Схема A» (7 полей учёта): link/auth status, session_count, attenuation,
    equipment_owned, warranty, repeat_claim
  * «Схема B» (24 поля FTTx-диагностики): port_status, pppoe/dhcp/dns, ping,
    errors_crc, wifi_rssi, cable_length, equipment_type, адрес и т.д.

Один dataclass `Claim` — источник правды для всего конвейера.
Функция `normalize()` приводит старые схемы A / B к единому виду,
чтобы старые данные и коннекторы не ломали пайплайн.
"""
from dataclasses import dataclass, fields
from typing import Optional


ACTION_NAMES = {0: "Дистанционно", 1: "Звонок", 2: "Выезд"}
ACTION_CODES = {"Дистанционно": 0, "Звонок": 1, "Выезд": 2}

EQUIPMENT_TYPES = ["роутер", "приставка", "медиаконвертер", "ONT", "коммутатор"]

NUMERIC_FIELDS = [
    "link_status", "auth_status", "session_count", "attenuation_db",
    "pppoe_status", "dhcp_status", "dns_status", "ping_gateway_ms",
    "ping_dns_ms", "errors_crc", "wifi_rssi", "power_poe",
    "speed_duplex", "cable_length_m", "equipment_owned", "warranty",
    "rental", "repeat_claim", "vlan_id", "mac_binding",
]
ADDRESS_FIELDS = ["street", "building", "entrance", "floor"]
CATEGORICAL_FIELDS = ["equipment_type"]

# Признаки для ML-классификатора (числовые + код оборудования).
FEATURE_NUMERIC = list(NUMERIC_FIELDS) + ["equipment_code"]


def _i(v, default=0):
    """Безопасное приведение к int (0 — валидное значение, не заменяется)."""
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default


def _f(v, default=0.0):
    """Безопасное приведение к float."""
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


@dataclass
class Claim:
    # --- текст заявки (свободная форма) ---
    text: str
    claim_id: Optional[str] = None

    # --- сетевые признаки ---
    link_status: int = 1          # 0 — линк DOWN, 1 — UP
    auth_status: int = 1          # 0 — авторизация не прошла, 1 — OK
    session_count: int = 0        # кол-во переподключений/сессий
    attenuation_db: float = 15.0  # затухание сигнала, dB
    pppoe_status: int = 1
    dhcp_status: int = 1
    dns_status: int = 1
    ping_gateway_ms: int = 20
    ping_dns_ms: int = 30
    errors_crc: int = 0
    wifi_rssi: int = -50          # уровень сигнала Wi-Fi, dBm
    power_poe: int = 1            # PoE-питание
    speed_duplex: int = 1         # 0/1/2 → 10M/100M/1G
    cable_length_m: int = 80
    vlan_id: int = 100
    mac_binding: int = 1

    # --- оборудование / учёт ---
    equipment_type: str = "роутер"
    equipment_owned: int = 1      # 0 — не наше, 1 — наше
    warranty: int = 1
    rental: int = 0
    repeat_claim: int = 0

    # --- адрес (для выезда) ---
    street: str = ""
    building: str = ""
    entrance: int = 0
    floor: int = 0

    # --- метка (только в обучающих данных) ---
    true_action: Optional[int] = None

    def equipment_code(self) -> int:
        return EQUIPMENT_TYPES.index(self.equipment_type) if self.equipment_type in EQUIPMENT_TYPES else 0

    def to_feature_dict(self) -> dict:
        d = {f: getattr(self, f) for f in NUMERIC_FIELDS}
        d["equipment_code"] = self.equipment_code()
        return d

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def address_str(self) -> str:
        parts = [p for p in [self.street, str(self.building) if self.building else "",
                             f"под. {self.entrance}" if self.entrance else "",
                             f"эт. {self.floor}" if self.floor else ""] if p]
        return " ".join(parts)


def normalize(raw: dict) -> Claim:
    """
    Приводит устаревшую схему (старой схемы A (7 полей) или B (24 поля, FTTx)) к единому контракту Claim.
    Неизвестные/отсутствующие поля заполняются разумными значениями по умолчанию.
    """
    text = str(raw.get("text", ""))
    claim_id = raw.get("claim_id")
    true_action = _i(raw.get("true_action")) if raw.get("true_action") is not None else None

    # ---- Схема A: учётная (7 полей) ----
    if "linq_status" in raw or "attenuation" in raw:
        link = _i(raw.get("linq_status", 1))
        auth = _i(raw.get("auth_status", 1))
        sessions = _i(raw.get("session_count", 0))
        atten = _f(raw.get("attenuation", 15.0))
        return Claim(
            text=text, claim_id=claim_id,
            link_status=link, auth_status=auth, session_count=sessions,
            attenuation_db=atten,
            pppoe_status=auth, dhcp_status=auth, dns_status=auth,
            # грубые оценки из признаков схемы A (для совместимости с ML-признаками)
            ping_gateway_ms=int(20 + max(0.0, atten - 15) * 3),
            ping_dns_ms=int(30 + max(0.0, atten - 15) * 4),
            errors_crc=int(max(0.0, atten - 30) * 2),
            wifi_rssi=-50, power_poe=1, speed_duplex=1, cable_length_m=80,
            vlan_id=100, mac_binding=1, equipment_type="роутер",
            equipment_owned=_i(raw.get("equipment_owned", 1)),
            warranty=_i(raw.get("warranty", 1)),
            rental=0, repeat_claim=_i(raw.get("repeat_claim", 0)),
            true_action=true_action,
        )

    # ---- Схема FTTx (app.py) ----
    port = _i(raw.get("port_status", 1))
    pppoe = _i(raw.get("pppoe_status", 1))
    dhcp = _i(raw.get("dhcp_status", 1))
    dns = _i(raw.get("dns_resolution", 1))
    auth = 1 if (pppoe and dhcp and dns) else 0
    ping_gw = _i(raw.get("ping_gateway", 20))
    ping_dns = _i(raw.get("ping_dns", 30))
    crc = _i(raw.get("errors_crc", 0))
    cable = _i(raw.get("cable_length", 80))
    atten = round((max(0, ping_gw - 20) * 0.3 + max(0, crc - 10) * 0.4
                   + max(0, cable - 80) * 0.05 + 10), 1)
    return Claim(
        text=text, claim_id=claim_id,
        link_status=port, auth_status=auth,
        session_count=_i(raw.get("link_flaps", 0)),
        attenuation_db=atten,
        pppoe_status=pppoe, dhcp_status=dhcp, dns_status=dns,
        ping_gateway_ms=ping_gw, ping_dns_ms=ping_dns, errors_crc=crc,
        wifi_rssi=_i(raw.get("wifi_rssi", -50)),
        power_poe=_i(raw.get("power_poe", 1)),
        speed_duplex=_i(raw.get("speed_duplex", 1)),
        cable_length_m=cable, vlan_id=_i(raw.get("vlan_id", 100)),
        mac_binding=_i(raw.get("mac_binding", 1)),
        equipment_type=str(raw.get("equipment_type", "роутер")),
        equipment_owned=_i(raw.get("equipment_owned", 1)),
        warranty=_i(raw.get("warranty", 1)),
        rental=_i(raw.get("rental", 0)),
        repeat_claim=_i(raw.get("repeat_claim", 0)),
        street=str(raw.get("street", "")), building=str(raw.get("building", "")),
        entrance=_i(raw.get("entrance", 0)), floor=_i(raw.get("floor", 0)),
        true_action=true_action,
    )
