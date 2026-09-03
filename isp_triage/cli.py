# -*- coding: utf-8 -*-
"""
cli.py — консольный интерфейс конвейера.

Команды:
  python -m isp_triage.cli train       сгенерировать данные (если нет) и обучить ML
  python -m isp_triage.cli evaluate    честные метрики (accuracy/precision/recall/F1)
  python -m isp_triage.cli demo [-n N] прогнать N заявок через конвейер и показать трассу
"""
import argparse
import os
import sys

# Принудительный UTF-8 вывод (emoji не падают в Windows-консоли cp1251).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

from isp_triage.data import generate as gen
from isp_triage.triage import classifier as clf_mod
from isp_triage.pipeline import process
from isp_triage.connectors.workorders import WorkOrderConnector
from isp_triage.contract import Claim, ACTION_NAMES


def _ensure_data() -> pd.DataFrame:
    if not os.path.exists(gen.DATA_FILE):
        print("📊 Датасет не найден — генерируем синтетику...")
        gen.generate_synthetic(1000)
    return pd.read_csv(gen.DATA_FILE, encoding="utf-8-sig")


def cmd_train(args):
    df = _ensure_data()
    print("🧠 Обучение ML-триажа...")
    m = clf_mod.train(df)
    print(f"✅ Accuracy={m['accuracy']:.3f}  Precision={m['precision']:.3f}  "
          f"Recall={m['recall']:.3f}  F1={m['f1']:.3f}")


def cmd_evaluate(args):
    df = _ensure_data()
    m = clf_mod.evaluate(df)
    if not m:
        print("❌ Модель не найдена. Сначала: python -m isp_triage.cli train")
        return
    print(f"📏 Метрики на {len(df)} заявках:")
    print(f"   Accuracy ={m['accuracy']:.3f}")
    print(f"   Precision={m['precision']:.3f}")
    print(f"   Recall   ={m['recall']:.3f}")
    print(f"   F1       ={m['f1']:.3f}")
    print("\n   По классам:")
    for name in ("Дистанционно", "Звонок", "Выезд"):
        r = m["report"].get(name)
        if r:
            print(f"     {name:12s} P={r['precision']:.2f} R={r['recall']:.2f} "
                  f"F1={r['f1-score']:.2f} support={int(r['support'])}")


def cmd_demo(args):
    df = _ensure_data()
    wos = WorkOrderConnector()
    n = args.n if args.n and args.n > 0 else 5
    sample = df.head(n)
    print(f"\n=== Демо конвейера на {len(sample)} заявках ===\n")
    for _, row in sample.iterrows():
        claim = Claim(**{k: v for k, v in row.items()
                         if k in Claim.__dataclass_fields__})
        res = process(claim, wos)
        print(f"📝 #{claim.claim_id} {claim.text}")
        print(f"   ➜ {res.action_name}  (источник: {res.source}, "
              f"уверенность: {res.confidence:.2f})")
        print(f"   💡 {res.diagnosis}")
        for s in res.instructions:
            print(f"      - {s}")
        if res.wo_ref:
            print(f"   🔗 WOS: {res.wo_ref['order_id']} ({res.wo_ref['status']})")
        if res.rules_flag:
            print(f"   ⚠️ Жёсткое правило расходилось с ML!")
        print()


def main():
    p = argparse.ArgumentParser(description="ИИ-ассистент инженера оператора связи (конвейер Б).")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("train", help="обучить ML-триаж")
    sub.add_parser("evaluate", help="честные метрики")
    pd_ = sub.add_parser("demo", help="прогнать заявки через конвейер")
    pd_.add_argument("-n", type=int, default=5, help="число заявок")
    args = p.parse_args()

    handlers = {"train": cmd_train, "evaluate": cmd_evaluate, "demo": cmd_demo}
    handlers.get(args.cmd or "demo", cmd_demo)(args)


if __name__ == "__main__":
    main()
