# -*- coding: utf-8 -*-
"""
data/generate.py — генерация СИНТЕТИЧЕСКОГО датасета в едином контракте.

ВАЖНО: данные синтетические и служат только для демонстрации конвейера.
Для честной метрики нужны реальные выгрузки заявок из Helpdesk + разметка
эксперта (см. README, раздел «Roadmap»). Здесь метки привязаны к признакам,
поэтому ML учится детерминированно и метрики высокие — это ожидаемо для макета.
"""
import os
import random
import sys

# Принудительный UTF-8 вывод.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(_BASE, "data", "claims.csv")

random.seed(42)

STREETS = ["Ленина", "Гагарина", "Мира", "Победы", "Советская", "Кирова", "Пушкина"]
EQUIP = ["роутер", "приставка", "медиаконвертер", "ONT", "коммутатор"]

# Тексты, коррелирующие с меткой действия.
TEXT_BY_ACTION = {
    0: [  # Дистанционно
        "ТВ-приставка не показывает каналы, пульт не реагирует",
        "Не могу войти в личный кабинет, ошибка 403",
        "После перезагрузки роутера всё заработало",
        "Файрвол включён, интернет не работает, отключите его",
        "Настройте DNS, сайты не открываются",
        "Сбросьте PPPoE-сессию на коммутаторе",
        "Пульт не переключает каналы на ТВ-приставке",
        "Переподключите питание приставки",
    ],
    1: [  # Звонок
        "Низкая скорость, уточните настройки у абонента",
        "Wi-Fi отключается, спросите про торрент",
        "SIP не регистрируется, уточните логин и пароль",
        "Медленно грузит, выясните количество устройств",
        "Проверьте настройки роутера по телефону",
        "Уточните, не было ли повреждений кабеля",
    ],
    2: [  # Выезд
        "Собака перегрызла кабель, интернет пропал",
        "Полный обрыв, линка нет вообще",
        "Соседи порвали кабель при копании, связи нет",
        "Сгорел блок питания роутера, не включается",
        "Порт на коммутаторе DOWN",
        "Обрыв магистрального кабеля, район без интернета",
        "Кабель оборван, видны голые провода",
        "Приставка не включается совсем",
    ],
}

PREFIXES = ["Срочно!", "Помогите!", "Уже второй день", "Не знаю, что делать,"]


def _fill(action: int) -> dict:
    """Генерирует признаки, согласованные с меткой действия."""
    text = random.choice(TEXT_BY_ACTION[action])
    if random.random() < 0.2:
        text = random.choice(PREFIXES) + " " + text

    if action == 0:  # Дистанционно — всё в норме, линк UP
        link, auth = 1, 1
        pppoe = dhcp = dns = 1
        ping_gw = random.randint(5, 30)
        ping_dns = random.randint(5, 40)
        crc = random.randint(0, 5)
        sess = random.randint(0, 3)
        atten = round(random.uniform(5, 20), 1)
    elif action == 1:  # Звонок — чаще живо, но есть нюансы
        link = 1
        auth = random.choice([0, 1, 1])
        pppoe = random.choice([0, 1, 1])
        dhcp = random.choice([0, 1, 1])
        dns = random.choice([0, 1, 1])
        ping_gw = random.randint(20, 80)
        ping_dns = random.randint(30, 120)
        crc = random.randint(0, 20)
        sess = random.randint(0, 10)
        atten = round(random.uniform(10, 30), 1)
    else:  # Выезд — физическая неисправность
        link = random.choices([0, 1], weights=[0.7, 0.3])[0]
        auth = random.choices([0, 1], weights=[0.5, 0.5])[0]
        pppoe = dhcp = dns = random.choices([0, 1], weights=[0.4, 0.6])[0]
        ping_gw = random.randint(50, 200)
        ping_dns = random.randint(80, 300)
        crc = random.randint(40, 90)
        sess = random.randint(10, 30)
        atten = round(random.uniform(30, 45), 1)

    return {
        "link_status": link,
        "auth_status": auth,
        "session_count": sess,
        "attenuation_db": atten,
        "pppoe_status": pppoe,
        "dhcp_status": dhcp,
        "dns_status": dns,
        "ping_gateway_ms": ping_gw,
        "ping_dns_ms": ping_dns,
        "errors_crc": crc,
        "wifi_rssi": random.randint(-90, -40),
        "power_poe": random.choices([0, 1], weights=[0.15, 0.85])[0],
        "speed_duplex": random.choice([0, 1, 1, 2]),
        "cable_length_m": random.randint(30, 150),
        "vlan_id": random.choice([100, 200, 300]),
        "mac_binding": random.choice([0, 1]),
        "equipment_type": random.choice(EQUIP),
        "equipment_owned": random.choices([0, 1], weights=[0.2, 0.8])[0],
        "warranty": random.choices([0, 1], weights=[0.4, 0.6])[0],
        "rental": random.choices([0, 1], weights=[0.7, 0.3])[0],
        "repeat_claim": random.choices([0, 1], weights=[0.7, 0.3])[0],
        "street": random.choice(STREETS),
        "building": str(random.randint(1, 50)),
        "entrance": random.randint(1, 5),
        "floor": random.randint(1, 10),
        "text": text,
    }


def generate_synthetic(num_samples: int = 1000, path: str = None) -> str:
    path = path or DATA_FILE
    action_weights = [0.5, 0.3, 0.2]  # дист / звонок / выезд
    rows = []
    for i in range(num_samples):
        action = random.choices([0, 1, 2], weights=action_weights)[0]
        row = _fill(action)
        row["claim_id"] = i + 1
        row["true_action"] = action
        rows.append(row)

    cols = [
        "claim_id", "text", "link_status", "auth_status", "session_count",
        "attenuation_db", "pppoe_status", "dhcp_status", "dns_status",
        "ping_gateway_ms", "ping_dns_ms", "errors_crc", "wifi_rssi",
        "power_poe", "speed_duplex", "cable_length_m", "vlan_id",
        "mac_binding", "equipment_type", "equipment_owned", "warranty",
        "rental", "repeat_claim", "street", "building", "entrance", "floor",
        "true_action",
    ]
    df = pd.DataFrame(rows)[cols]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"✅ Сгенерирован датасет: {path} ({len(df)} заявок)")
    print(df["true_action"].value_counts().sort_index()
          .rename({0: "Дистанционно", 1: "Звонок", 2: "Выезд"}).to_string())
    return path


if __name__ == "__main__":
    generate_synthetic(1000)
