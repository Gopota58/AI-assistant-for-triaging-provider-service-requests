# -*- coding: utf-8 -*-
"""
connectors/workorders.py — ЗАГЛУШКА интеграции WOS (Work Order System).

В боевой системе здесь: авторизация, открытие сессии, привязка заявки к
абоненту, чтение затухания/линка, создание наряда. В прототипе возвращаем
mock-ссылку и логируем намерение, чтобы продемонстрировать место интеграции
в конвейере без реальных сайд-эффектов.
"""
import uuid

from isp_triage.contract import Claim, ACTION_NAMES


class WorkOrderConnector:
    def create_work_order(self, claim: Claim, action: int) -> dict:
        """Создаёт (mock) наряд в WOS и возвращает ссылку."""
        order_id = "WO-" + uuid.uuid4().hex[:8].upper()
        # Реальная интеграция: авторизация → сессия → привязка абонента →
        # запись действия (Дистанционно/Звонок/Выезд) → затухание/линк.
        return {
            "order_id": order_id,
            "status": "created(mock)",
            "action": ACTION_NAMES.get(action, str(action)),
            "claim_id": claim.claim_id,
            "note": "Заглушка WOS: реальная интеграция не подключена.",
        }

    def create_incident(self, claim: Claim, outage: dict) -> dict:
        """Создаёт (mock) сетевой инцидент на узле вместо абонентского наряда."""
        inc_id = "INC-" + uuid.uuid4().hex[:8].upper()
        return {
            "order_id": inc_id,
            "status": "incident(mock)",
            "action": "Авария на узле",
            "claim_id": claim.claim_id,
            "note": f"Объединяет заявки по {outage.get('id','?')} → узловая бригада.",
        }
