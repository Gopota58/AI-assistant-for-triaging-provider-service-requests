# -*- coding: utf-8 -*-
"""Тесты единого контракта Claim и normalize()."""
from isp_triage.contract import Claim, FEATURE_NUMERIC, normalize


def test_normalize_schema_a_basic():
    """Легаси «схема A» (7 полей учёта) → единый контракт."""
    c = normalize({"text": "обрыв", "linq_status": 0, "auth_status": 0,
                   "session_count": 5, "attenuation": 42.0,
                   "equipment_owned": 1, "warranty": 0, "repeat_claim": 1,
                   "true_action": 2})
    assert c.link_status == 0
    assert c.attenuation_db == 42.0
    assert c.session_count == 5
    assert c.repeat_claim == 1
    assert c.true_action == 2
    # производные поля согласуются с авторизацией
    assert c.pppoe_status == 0 and c.dhcp_status == 0


def test_normalize_schema_b_auth_derived():
    """«Схема B»: auth выводится из pppoe/dhcp/dns, dns_resolution → dns_status."""
    c = normalize({"text": "нет интернета", "port_status": 1,
                   "pppoe_status": 0, "dhcp_status": 1, "dns_resolution": 1,
                   "ping_gateway": 40, "errors_crc": 12, "cable_length": 100})
    assert c.link_status == 1
    assert c.auth_status == 0          # pppoe упал → авторизации нет
    assert c.dns_status == 1
    assert c.cable_length_m == 100
    assert c.attenuation_db > 10       # оценка из ping/crc/cable


def test_normalize_unknown_defaults():
    """Пустой словарь не роняет normalize — дефолты валидны."""
    c = normalize({})
    assert isinstance(c, Claim)
    assert c.link_status == 1 and c.auth_status == 1
    assert c.true_action is None


def test_normalize_garbage_numbers_safe():
    """Мусор в числовых полях не роняет normalize — безопасный фолбэк 0."""
    c = normalize({"text": "x", "attenuation": "n/a", "session_count": None})
    assert c.attenuation_db == 0.0   # безопасный дефолт вместо падения
    assert c.session_count == 0


def test_feature_dict_keys():
    c = Claim(text="t")
    d = c.to_feature_dict()
    assert set(d.keys()) == set(FEATURE_NUMERIC)
    assert d["equipment_code"] == c.equipment_code()


def test_address_str():
    c = Claim(text="t", street="Ленина", building="5", entrance=3, floor=4)
    assert c.address_str() == "Ленина 5 под. 3 эт. 4"
    assert Claim(text="t").address_str() == ""
