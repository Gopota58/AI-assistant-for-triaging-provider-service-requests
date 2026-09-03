# -*- coding: utf-8 -*-
"""
feedback.py — human-in-the-loop: журнал правок инженера и дообучение.

Инженер подтверждает/исправляет/отклоняет решение ассистента. Каждая правка:
  1) пишется в data/feedback.csv (журнал для метрик согласия);
  2) дописывается как помеченный пример в data/claims_feedback.csv —
     из него модель дообучается (реальный цикл обратной связи).
"""
import os
import time

import pandas as pd

from isp_triage.contract import Claim

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEEDBACK_CSV = os.path.join(_BASE, "data", "feedback.csv")
LABELED_CSV = os.path.join(_BASE, "data", "claims_feedback.csv")


def _append(path: str, row: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = not os.path.exists(path)
    pd.DataFrame([row]).to_csv(path, mode="a", header=header, index=False,
                               encoding="utf-8-sig")


def record(claim: Claim, predicted: int, corrected: int, comment: str = ""):
    _append(FEEDBACK_CSV, {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "claim_id": claim.claim_id,
        "text": claim.text,
        "predicted": predicted,
        "corrected": corrected,
        "changed": int(predicted != corrected),
        "comment": comment,
    })
    # помеченный пример для дообучения
    d = claim.to_dict()
    d["true_action"] = corrected
    _append(LABELED_CSV, d)


def stats() -> dict:
    if not os.path.exists(FEEDBACK_CSV):
        return {"total": 0, "changed": 0, "agreement": 1.0}
    df = pd.read_csv(FEEDBACK_CSV, encoding="utf-8-sig")
    total = len(df)
    changed = int(df["changed"].sum())
    return {"total": total, "changed": changed,
            "agreement": (1 - changed / total) if total else 1.0}


def recent(n: int = 30):
    if not os.path.exists(FEEDBACK_CSV):
        return pd.DataFrame()
    df = pd.read_csv(FEEDBACK_CSV, encoding="utf-8-sig")
    return df.tail(n).iloc[::-1].reset_index(drop=True)


def labeled_path() -> str:
    return LABELED_CSV
