# -*- coding: utf-8 -*-
"""
triage/classifier.py — ML-триаж заявок (Вариант Б).

Роль: быстрый, детерминированный, ИЗМЕРИМЫЙ маршрутизатор
«Дистанционно / Звонок / Выезд». Работает на едином контракте Claim.
LLM подключается точечно поверх (см. llm/engine.py и pipeline.py).
"""
import os
import pickle
import warnings

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split
from sklearn.metrics import (accuracy_score, precision_recall_fscore_support,
                             classification_report)

from isp_triage.contract import Claim, ACTION_NAMES, FEATURE_NUMERIC

warnings.filterwarnings("ignore")

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_FILE = os.path.join(_BASE, "models", "model.pkl")

# Кэш загруженной модели (иначе каждый predict читает и unpickle-ит ~10 МБ).
_MODEL_CACHE = None


def _claims_to_X(claims, tfidf):
    rows = [c.to_feature_dict() for c in claims]
    Xnum = pd.DataFrame(rows)
    text = [c.text for c in claims]
    T = tfidf.transform(text).toarray()
    Tdf = pd.DataFrame(T, columns=[f"tfidf_{i}" for i in range(T.shape[1])])
    return pd.concat([Xnum.reset_index(drop=True), Tdf], axis=1)


def _claims_from_df(df: pd.DataFrame):
    claims = []
    for row in df.to_dict("records"):
        row = {k: v for k, v in row.items() if k in Claim.__dataclass_fields__}
        claims.append(Claim(**row))
    return claims


def train(df: pd.DataFrame, test_size: float = 0.2) -> dict:
    """Обучает модель и возвращает метрики на отложенной выборке."""
    claims = _claims_from_df(df)
    y = df["true_action"].astype(int).values
    claims_tr, claims_te, y_tr, y_te = train_test_split(
        claims, y, test_size=test_size, random_state=42, stratify=y)

    tfidf = TfidfVectorizer(max_features=80, stop_words="english", ngram_range=(1, 2))
    tfidf.fit([c.text for c in claims])
    Xtr = _claims_to_X(claims_tr, tfidf)

    clf = RandomForestClassifier(
        n_estimators=300, max_depth=16, min_samples_split=4,
        class_weight="balanced", random_state=42)
    clf.fit(Xtr, y_tr)

    os.makedirs(os.path.dirname(MODEL_FILE), exist_ok=True)
    with open(MODEL_FILE, "wb") as f:
        pickle.dump((clf, tfidf, FEATURE_NUMERIC), f)
    global _MODEL_CACHE
    _MODEL_CACHE = None  # инвалидируем кэш после переобучения

    return _score(clf, tfidf, claims_te, y_te)


def load_model():
    global _MODEL_CACHE
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE
    if os.path.exists(MODEL_FILE):
        try:
            with open(MODEL_FILE, "rb") as f:
                _MODEL_CACHE = pickle.load(f)
            return _MODEL_CACHE
        except Exception as e:
            print(f"⚠️ Не удалось загрузить модель ({e}); требуется переобучение.")
            return None, None, None
    return None, None, None


def predict(claim: Claim):
    """Возвращает (action, confidence, probs)."""
    clf, tfidf, _ = load_model()
    if clf is None:
        raise RuntimeError(
            "Модель не обучена. Запустите: python -m isp_triage.cli train")
    X = _claims_to_X([claim], tfidf)
    probs = clf.predict_proba(X)[0]
    action = int(np.argmax(probs))
    return action, float(np.max(probs)), probs


def _score(clf, tfidf, claims, y_true):
    if len(claims) == 0:
        return {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0,
                "report": {}}
    X = _claims_to_X(claims, tfidf)
    yp = clf.predict(X)
    acc = accuracy_score(y_true, yp)
    prec, rec, f1, _ = precision_recall_fscore_support(
        y_true, yp, average="weighted", zero_division=0)
    labels = sorted(set(list(y_true) + list(yp)))
    rep = classification_report(
        y_true, yp, labels=labels,
        target_names=[ACTION_NAMES[i] for i in labels],
        output_dict=True, zero_division=0)
    return {"accuracy": acc, "precision": prec, "recall": rec, "f1": f1, "report": rep}


def evaluate(df: pd.DataFrame) -> dict:
    """Честные метрики на всём датасете (модель уже обучена)."""
    clf, tfidf, _ = load_model()
    if clf is None:
        return None
    claims = _claims_from_df(df)
    y = df["true_action"].astype(int).values
    return _score(clf, tfidf, claims, y)
