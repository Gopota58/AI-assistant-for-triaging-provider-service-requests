# -*- coding: utf-8 -*-
"""
audit.py — журнал решений (для L3 важен аудит: кто/что/почему/с какой уверенностью).

Каждое решение конвейера пишется одной JSON-строкой в data/audit.log.
"""
import json
import os
import time

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIT = os.path.join(_BASE, "data", "audit.log")


def log(entry: dict):
    os.makedirs(os.path.dirname(AUDIT), exist_ok=True)
    entry = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), **entry}
    with open(AUDIT, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def recent(n: int = 100):
    if not os.path.exists(AUDIT):
        return []
    with open(AUDIT, encoding="utf-8") as f:
        lines = f.readlines()[-n:]
    out = []
    for ln in reversed(lines):
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    return out
