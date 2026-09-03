# -*- coding: utf-8 -*-
"""
connectors/helpdesk.py — ЗАГЛУШКА read-only источника заявок (Helpdesk).

В боевой системе здесь должен быть read-only вызов API Helpdesk для выгрузки
потока заявок техподдержки. В прототипе читаем локальный CSV (единый контракт).
Интерфейс намеренно простой, чтобы реальную интеграцию подставить без
изменения пайплайна.
"""
import os

import pandas as pd

from isp_triage.contract import Claim, normalize

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CSV = os.path.join(_BASE, "data", "claims.csv")


class HelpdeskConnector:
    def __init__(self, source_csv: str = None):
        self.source_csv = source_csv or _DEFAULT_CSV

    def fetch_claims(self, limit: int = 20, with_labels: bool = False):
        """
        Возвращает список Claim.
        with_labels=True — оставить true_action (для офлайн-метрик).
        """
        if not os.path.exists(self.source_csv):
            raise RuntimeError(
                f"Нет файла данных {self.source_csv}. "
                f"Сначала: python -m isp_triage.cli train")
        df = pd.read_csv(self.source_csv, encoding="utf-8-sig")
        if limit:
            df = df.head(limit)
        out = []
        for _, row in df.iterrows():
            raw = row.to_dict()
            if not with_labels:
                raw.pop("true_action", None)
            out.append(normalize(raw))
        return out
