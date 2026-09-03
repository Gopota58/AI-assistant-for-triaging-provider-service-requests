# -*- coding: utf-8 -*-
"""Тесты жёстких правил-валидатора (физика сети)."""
from isp_triage.contract import Claim
from isp_triage.triage.rules import validate


def test_rule_full_outage():
    c = Claim(text="ничего нет", link_status=0, auth_status=0)
    action, reason = validate(c)
    assert action == 2 and "обрыв" in reason.lower()


def test_rule_link_down_only():
    c = Claim(text="порт down", link_status=0, auth_status=1)
    action, _ = validate(c)
    assert action == 2


def test_rule_critical_attenuation():
    c = Claim(text="тормозит", link_status=1, attenuation_db=45.0)
    action, reason = validate(c)
    assert action == 2 and "затухание" in reason.lower()


def test_rule_crc_storm():
    c = Claim(text="ошибки", link_status=1, attenuation_db=10, errors_crc=60)
    action, _ = validate(c)
    assert action == 2


def test_rule_foreign_equipment():
    c = Claim(text="роутер не наше оборудование, чужое", link_status=1, equipment_owned=0)
    action, _ = validate(c)
    assert action == 2


def test_rule_pet_damage():
    c = Claim(text="Собака перегрызла кабель", link_status=1, attenuation_db=10)
    action, reason = validate(c)
    assert action == 2 and "животн" in reason.lower()


def test_rule_silent_on_healthy_claim():
    c = Claim(text="не работает dns", link_status=1, auth_status=1,
              attenuation_db=12, errors_crc=0, equipment_owned=1)
    assert validate(c) == (None, None)
