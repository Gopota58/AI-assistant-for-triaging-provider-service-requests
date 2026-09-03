# -*- coding: utf-8 -*-
"""Общие фикстуры тестов."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from isp_triage.data import generate as gen  # noqa: E402
from isp_triage.triage import classifier as clf_mod  # noqa: E402


@pytest.fixture(scope="session")
def trained_model(tmp_path_factory):
    """Один раз на сессию: маленькая синтетика + обучение ML-триажа."""
    path = str(tmp_path_factory.mktemp("data") / "claims_small.csv")
    gen.generate_synthetic(300, path=path)
    import pandas as pd
    df = pd.read_csv(path, encoding="utf-8-sig")
    metrics = clf_mod.train(df)
    assert metrics["accuracy"] > 0.8, "модель не выучила синтетику"
    return df
