# -*- coding: utf-8 -*-
"""
app.py — веб-демо конвейера (Вариант Б, уровень L3) на Streamlit.

Запуск из корня проекта:
    python -m streamlit run isp_triage/app.py --server.headless true

Вкладки:
  1. 📊 Обзор    — ценность, как работает, симулятор экономии.
  2. 🗂️ Очередь  — список заявок в стиле Helpdesk: фильтры, поиск, карточка, фидбек.
  3. 🎛️ Заявка   — ручной ввод одной заявки + разбор.
  4. 📡 Поток    — живая диспетчерская: KPI, экономия, разворачиваемая лента.
  5. 🧠 Обучение — human-in-the-loop: правки инженера и дообучение модели.
  6. 📜 Журнал   — аудит всех решений.
  7. ✅ Качество — метрики на синтетике (с честной оговоркой).
"""
import os
import sys
import time

import streamlit as st
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from isp_triage.contract import Claim, ACTION_NAMES
from isp_triage.pipeline import process
from isp_triage.connectors.helpdesk import HelpdeskConnector
from isp_triage.connectors.workorders import WorkOrderConnector
from isp_triage.data import generate as gen
from isp_triage.triage import classifier as clf_mod
from isp_triage import impact, feedback, audit, topology

ACTION_COLOR = {0: "#2e7d32", 1: "#ef6c00", 2: "#c62828"}
ACTION_ICON = {0: "🖥️", 1: "📞", 2: "🚚"}

STYLE = """
<style>
.banner{background:linear-gradient(90deg,#0b3d91,#1565c0);color:#fff;padding:16px 20px;border-radius:12px;margin-bottom:14px;box-shadow:0 2px 8px rgba(0,0,0,.15);}
.banner b{font-size:22px;}
.banner span{opacity:.85;font-size:13px;margin-left:8px;}
.badge{display:inline-block;padding:3px 12px;border-radius:14px;color:#fff;font-weight:700;font-size:14px;}
.kpi{border:1px solid #e3e6ea;border-radius:12px;padding:14px;text-align:center;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.05);}
.kpi .v{font-size:24px;font-weight:800;}
.kpi .l{font-size:12px;color:#666;margin-top:2px;}
.card{border:1px solid #e3e6ea;border-radius:12px;padding:16px;margin:10px 0;background:#fff;}
.card.outage{border-color:#c62828;background:#fff5f5;}
.card h4{margin:0 0 8px;}
.param{font-size:13px;color:#444;min-width:120px;}
.steprow{display:flex;gap:8px;align-items:stretch;margin:12px 0;flex-wrap:wrap;}
.stepcard{flex:1;min-width:120px;padding:12px 10px;border-radius:10px;text-align:center;border:1px solid #e0e0e0;}
.stepcard .st{font-size:13px;font-weight:700;}
.stepcard .sv{margin-top:6px;font-size:12px;color:#444;}
.step-ml{background:#eef4fc;border-color:#1565c0;}
.step-rule{background:#fdecea;border-color:#c62828;}
.step-llm{background:#f3eafb;border-color:#6a1b9a;}
.step-wos{background:#eaf5ec;border-color:#2e7d32;}
.step-corr{background:#fff3e0;border-color:#e65100;}
.step-muted{background:#f5f5f5;border-color:#ddd;color:#999;}
.arrow{display:flex;align-items:center;color:#aaa;font-size:22px;font-weight:700;}
.opinion{border:1px solid #e3e6ea;border-radius:10px;padding:12px;text-align:center;height:100%;}
.opinion.agree{box-shadow:0 0 0 2px #2e7d32 inset;}
.opinion.disagree{box-shadow:0 0 0 2px #c62828 inset;}
.dot{width:10px;height:10px;border-radius:50%;flex:0 0 auto;}
.hero{background:#f7f9fc;border:1px solid #e3e6ea;border-radius:12px;padding:18px 20px;margin-bottom:12px;}
.hero b{color:#0b3d91;}
.money{background:linear-gradient(90deg,#e8f5e9,#f1f8e9);border:1px solid #a5d6a7;border-radius:12px;padding:14px 18px;margin:10px 0;font-size:15px;}
.refs{background:#f3eafb;border:1px solid #ce93d8;border-radius:10px;padding:10px 14px;margin:8px 0;font-size:13px;}
</style>
"""


def badge(action, label=None):
    color = ACTION_COLOR.get(action, "#555")
    text = label or ACTION_NAMES.get(action, str(action))
    icon = ACTION_ICON.get(action, "")
    return f'<span class="badge" style="background:{color}">{icon} {text}</span>'


def kpi(value, label, color="#111"):
    return (f'<div class="kpi"><div class="v" style="color:{color}">{value}</div>'
            f'<div class="l">{label}</div></div>')


def _fmt(n):
    return f"{int(round(n)):,}".replace(",", " ")


def _tid(claim):
    return claim.claim_id if claim.claim_id not in (None, "") else abs(hash(claim.text))


def ticket_card(claim, res):
    items = [
        ("Линк", "DOWN" if claim.link_status == 0 else "UP"),
        ("Авторизация", "нет" if claim.auth_status == 0 else "есть"),
        ("PPPoE", "нет" if claim.pppoe_status == 0 else "есть"),
        ("DHCP", "нет" if claim.dhcp_status == 0 else "есть"),
        ("DNS", "нет" if claim.dns_status == 0 else "есть"),
        ("Затухание", f"{claim.attenuation_db} dB"),
        ("CRC", str(claim.errors_crc)),
        ("Ping шлюз", f"{claim.ping_gateway_ms} мс"),
        ("Переподключений", str(claim.session_count)),
        ("Оборудование", claim.equipment_type),
        ("Наше", "нет" if claim.equipment_owned == 0 else "да"),
        ("Гарантия", "нет" if claim.warranty == 0 else "есть"),
    ]
    params_html = "".join(
        f'<div class="param"><b>{k}:</b> {v}</div>' for k, v in items)
    inst_html = "".join(f"<li>{s}</li>" for s in res.instructions)
    addr = claim.address_str()
    addr_html = f"<p><b>📍 Адрес:</b> {addr}</p>" if addr else ""
    topo_html = ""
    if res.topo:
        topo_html = (f"<p class='muted'>🕸 Топология: {res.topo['olt']} → "
                     f"{res.topo['pon']} → {res.topo['cabinet']}</p>")
    wos_html = ""
    if res.wo_ref:
        wos_html = (f'<p>🔗 WOS: <b>{res.wo_ref["order_id"]}</b> '
                    f'({res.wo_ref["status"]})</p>')
    cls = "card outage" if res.final_kind == "outage" else "card"
    html = f"""
    <div class="{cls}">
      <h4>{badge(res.action)} &nbsp; Заявка #{claim.claim_id or "?"}</h4>
      <p><b>Текст:</b> {claim.text}</p>
      {addr_html}
      {topo_html}
      <div style="display:flex;flex-wrap:wrap;gap:6px 24px">{params_html}</div>
      <p style="margin-top:10px"><b>🩺 Диагноз:</b> {res.diagnosis}</p>
      <p><b>🛠 План работ:</b></p>
      <ul>{inst_html}</ul>
      {wos_html}
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def references_block(res):
    if not res.references:
        return
    rows = "".join(
        f"<li><b>{d['title']}</b> — <code>{d['ref']}</code>: {d['text']}</li>"
        for d in res.references)
    st.markdown(f'<div class="refs">📚 <b>База знаний (источники):</b><ul>{rows}</ul></div>',
                unsafe_allow_html=True)


def stepper(res):
    cards = [
        ("🚨 Корреляция",
         ("авария" if res.final_kind == "outage" else "нет аварии"),
         "step-corr" if res.final_kind == "outage" else "step-muted"),
        ("🤖 ML-триаж",
         (f"{ACTION_NAMES.get(res.ml_action,'?')} · {res.ml_confidence:.0%}"
          if res.final_kind != "outage" else "—"), "step-ml"),
        ("🛡️ Правила",
         (ACTION_NAMES.get(res.rules_action, "—") if res.rules_action is not None else "не сработали"),
         "step-rule" if res.rules_action is not None else "step-muted"),
        ("💬 LLM",
         (ACTION_NAMES.get(res.llm_action, "—") if res.llm_action is not None else "недоступен"),
         "step-llm" if res.llm_action is not None else "step-muted"),
        ("🔗 WOS",
         (res.wo_ref["order_id"] if res.wo_ref else "—"), "step-wos"),
    ]
    html = '<div class="steprow">'
    for i, (t, s, cls) in enumerate(cards):
        if i > 0:
            html += '<div class="arrow">→</div>'
        html += f'<div class="stepcard {cls}"><div class="st">{t}</div><div class="sv">{s}</div></div>'
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)
    if res.rules_flag:
        st.error("⚠️ Жёсткое правило перебило ML (приоритет безопасности).")


def _opinion_cell(title, action, caption, highlight):
    cls = "opinion " + (highlight or "")
    if action is None:
        body = '<div style="font-size:24px;color:#999">—</div>'
        cap = caption or ""
    else:
        body = badge(action)
        cap = caption or ""
    return (f'<div class="{cls}"><div style="font-weight:700;margin-bottom:6px">{title}</div>'
            f'{body}<div style="font-size:12px;color:#666;margin-top:6px">{cap}</div></div>')


def opinion_cards(res):
    st.markdown("**🧭 Мнения сторон**")
    ml, ru, ll = res.ml_action, res.rules_action, res.llm_action
    agreed = all(a == ml for a in (ru, ll) if a is not None)
    ml_hl = "agree" if agreed else ("disagree" if (
        (ru is not None and ru != ml) or (ll is not None and ll != ml)) else "")
    ru_hl = ("agree" if (ru is not None and ru == ml)
             else ("disagree" if ru is not None else ""))
    ll_hl = ("agree" if (ll is not None and ll == ml)
             else ("disagree" if ll is not None else ""))
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(_opinion_cell("🤖 ML-триаж", ml,
                   f"уверенность {res.ml_confidence:.0%}", ml_hl), unsafe_allow_html=True)
    with c2:
        st.markdown(_opinion_cell("🛡️ Жёсткие правила", ru,
                   (res.rules_reason or "не сработало")[:60], ru_hl), unsafe_allow_html=True)
    with c3:
        st.markdown(_opinion_cell("💬 LLM", ll,
                   (res.llm_diagnosis or "нет ollama")[:60], ll_hl), unsafe_allow_html=True)
    if agreed:
        st.success(f"✅ Все стороны согласны: {ACTION_NAMES[ml]}")
    elif res.rules_flag:
        st.error("⚠️ Жёсткое правило перебило ML (приоритет безопасности).")
    else:
        st.warning("⚠️ Мнения расходятся — требуется внимание оператора.")


def feedback_widget(claim, res, key_ns=""):
    tid = _tid(claim)
    st.markdown("**🧑‍🔧 Обратная связь инженера (human-in-the-loop):**")
    b1, b2, b3 = st.columns([1, 2, 1])
    if b1.button("👍 Верно", key=f"fbok_{key_ns}_{tid}"):
        feedback.record(claim, res.action, res.action)
        st.toast("Записано: решение верное")
        st.rerun()
    with b2:
        corr = st.selectbox("Исправить на", [0, 1, 2], index=res.action,
                            format_func=lambda x: ACTION_NAMES[x], key=f"fbsel_{key_ns}_{tid}")
        if st.button("✏️ Исправить", key=f"fbfix_{key_ns}_{tid}"):
            feedback.record(claim, res.action, corr)
            st.toast("Правка записана — модель дообучится")
            st.rerun()
    if b3.button("👎 Отклонить", key=f"fbrej_{key_ns}_{tid}"):
        feedback.record(claim, res.action, res.action, comment="rejected")
        st.toast("Отклонено")
        st.rerun()


def work_order_text(claim, res):
    order = res.wo_ref["order_id"] if res.wo_ref else "—"
    lines = [
        f"НАРЯД {order}",
        f"Заявка: #{claim.claim_id or '?'}",
        f"Решение: {res.action_name} (источник: {res.source})",
        f"Адрес: {claim.address_str() or '—'}",
        f"Текст: {claim.text}",
        "",
        f"Диагноз: {res.diagnosis}",
        "",
        "План работ:",
    ]
    lines += [f"  {i}. {s}" for i, s in enumerate(res.instructions, 1)]
    if res.references:
        lines += ["", "Источники (база знаний):"]
        lines += [f"  - {d['title']} — {d['ref']}" for d in res.references]
    return "\n".join(lines)


def render_result(claim, res, key_ns="", with_feedback=True):
    if res.final_kind == "outage":
        o = res.outage
        st.error(f"🚨 КОРРЕЛЯЦИЯ АВАРИЙ: {o['text']} · узел {o.get('olt','')} / "
                 f"{o['id']} · затронуто: {o['affected']}. Это НЕ абонентская "
                 f"неисправность — эскалация на узловую бригаду, индивидуальные выезды отменяются.")
    ticket_card(claim, res)
    references_block(res)
    if res.escalate and res.final_kind != "outage":
        st.warning("⬆️ Низкая уверенность — эскалация старшему инженеру (gating).")
    st.markdown("**🔄 Как принято решение**")
    stepper(res)
    if res.final_kind != "outage":
        opinion_cards(res)
    if with_feedback:
        feedback_widget(claim, res, key_ns)
    st.download_button(
        "⬇️ Скачать наряд (.txt)",
        data=work_order_text(claim, res).encode("utf-8"),
        file_name=f"order_{_tid(claim)}.txt", mime="text/plain",
        key=f"dl_{key_ns}_{_tid(claim)}", use_container_width=True)


def how_it_works():
    cards = [
        ("🚨 Корреляция", "Сначала: один абонент или авария на узле (OLT/PON)? Групповые — на узловую бригаду.", "step-corr"),
        ("🤖 ML-триаж", "Быстро и измеримо: Дистанционно / Звонок / Выезд.", "step-ml"),
        ("🛡️ Правила", "Однозначная физика (обрыв, критич. затухание) — приоритет.", "step-rule"),
        ("💬 LLM + 📚 БЗ", "Диагностика и план со ссылками на регламенты.", "step-llm"),
        ("🔗 WOS", "Наряд абонентский или сетевой инцидент (в демо — заглушка).", "step-wos"),
    ]
    html = '<div class="steprow">'
    for i, (t, d, cls) in enumerate(cards):
        if i > 0:
            html += '<div class="arrow">→</div>'
        html += f'<div class="stepcard {cls}"><div class="st">{t}</div><div class="sv">{d}</div></div>'
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)


def impact_panel(results, key_prefix="imp"):
    share = st.slider(
        "Допущение: доля абонентских заявок без выезда, ушедших бы на выезд",
        10, 100, 40, 5, key=f"{key_prefix}_share") / 100.0
    s = impact.summarize(results, baseline_share=share)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.markdown(kpi(s["total"], "Заявок обработано"), unsafe_allow_html=True)
    c2.markdown(kpi(f"{s['share_no_dispatch']:.0%}", "Без выезда", ACTION_COLOR[0]), unsafe_allow_html=True)
    c3.markdown(kpi(s["outage"], "🚨 По аварии узла", "#e65100"), unsafe_allow_html=True)
    c4.markdown(kpi(f"{_fmt(s['saved_hours'])} ч", "Экономия времени"), unsafe_allow_html=True)
    c5.markdown(kpi(f"{_fmt(s['saved_rub'])} ₽", "Экономия (оценка)", ACTION_COLOR[0]), unsafe_allow_html=True)
    st.caption("Оценка на условных допущениях (выезд ≈ 2 000 ₽ и ≈ 2 ч). В бою — из нормативов и данных Helpdesk/WOS.")
    return s


def run_pipeline(claim):
    return process(claim, WorkOrderConnector())


def _ensure_data():
    if not os.path.exists(gen.DATA_FILE):
        gen.generate_synthetic(1000)


def build_queue(n=40):
    _ensure_data()
    topology.reset_window()
    conn = HelpdeskConnector()
    claims = conn.fetch_claims(limit=n, with_labels=False)
    return [(c, run_pipeline(c)) for c in claims]


def main():
    st.set_page_config(page_title="ИИ-ассистент инженера (L3)", layout="wide")
    st.markdown(STYLE, unsafe_allow_html=True)
    st.markdown(
        '<div class="banner"><b>🤖 ИИ-ассистент инженера · 3-я линия</b>'
        '<span>диспетчерская заявок оператора связи · корреляция аварий + ML + правила + LLM + БЗ + WOS</span></div>',
        unsafe_allow_html=True)

    tab0, tabq, tab1, tab2, tabL, tabJ, tab3 = st.tabs(
        ["📊 Обзор", "🗂️ Очередь", "🎛️ Заявка", "📡 Поток",
         "🧠 Обучение", "📜 Журнал", "✅ Качество"])

    # ===================== Обзор =====================
    with tab0:
        st.markdown(
            '<div class="hero">Ассистент 3-й линии фильтрует заявки техподдержки и говорит, '
            '<b>что делать</b>: решить дистанционно, позвонить, ехать к абоненту — или '
            '<b>это массовая авария на узле</b> (тогда индивидуальные выезды не нужны). '
            'Выдаёт инженеру конкретный план работ со ссылками на регламенты и учится на его правках.</div>',
            unsafe_allow_html=True)
        st.markdown("#### ⚙️ Как это работает")
        how_it_works()
        st.markdown("#### 💰 Оценить эффект")
        st.caption("Прогоним поток заявок через конвейер и посчитаем потенциальную экономию.")
        if st.button("▶ Смоделировать 50 заявок"):
            _ensure_data()
            conn = HelpdeskConnector()
            claims = conn.fetch_claims(limit=50, with_labels=False)
            st.session_state.impact_results = [run_pipeline(c) for c in claims]
        results = st.session_state.get("impact_results")
        if results:
            s = impact_panel(results, key_prefix="ov")
            dist_df = pd.DataFrame({
                "Действие": [ACTION_NAMES[a] for a in (0, 1, 2)],
                "Кол-во": [s["by_action"][a] for a in (0, 1, 2)],
            }).set_index("Действие")
            st.bar_chart(dist_df, use_container_width=True)
            st.markdown(
                f'<div class="money">💡 За эти {s["total"]} заявок ассистент '
                f'объединил <b>{s["outage"]}</b> в сетевые инциденты по аварии и '
                f'предотвратил ≈ <b>{s["saved_rolls"]} выездов</b> — это '
                f'<b>{_fmt(s["saved_hours"])} часов</b> и ≈ <b>{_fmt(s["saved_rub"])} ₽</b>.</div>',
                unsafe_allow_html=True)
        else:
            st.info("Нажмите «▶ Смоделировать 50 заявок», чтобы увидеть цифры эффекта.")

    # ===================== Очередь (Helpdesk-style) =====================
    with tabq:
        st.subheader("🗂️ Очередь заявок (как в Helpdesk)")
        cA, cB = st.columns([3, 1])
        cA.caption("Список поступивших заявок. Выберите заявку, чтобы разобрать её и оставить обратную связь.")
        if cB.button("🔄 Обновить очередь", use_container_width=True):
            st.session_state["queue"] = build_queue(40)
        if "queue" not in st.session_state:
            st.session_state["queue"] = build_queue(40)
        queue = st.session_state["queue"]

        f1, f2, f3 = st.columns([3, 3, 1])
        search = f1.text_input("🔎 Поиск по тексту", key="q_search")
        acts = f2.multiselect("Действие", [0, 1, 2], default=[0, 1, 2],
                              format_func=lambda x: ACTION_NAMES[x], key="q_act")
        only_esc = f3.checkbox("Только эскалация", key="q_esc")

        filt = []
        for c, r in queue:
            if r.action not in acts:
                continue
            if search and search.lower() not in c.text.lower():
                continue
            if only_esc and not (r.escalate or r.final_kind == "outage"):
                continue
            filt.append((c, r))

        n_out = sum(1 for _, r in filt if r.final_kind == "outage")
        n_esc = sum(1 for _, r in filt if r.escalate)
        m1, m2, m3, m4 = st.columns(4)
        m1.markdown(kpi(len(filt), "В выборке"), unsafe_allow_html=True)
        m2.markdown(kpi(sum(1 for _, r in filt if r.action == 0), "🖥️ Дистанционно", ACTION_COLOR[0]), unsafe_allow_html=True)
        m3.markdown(kpi(n_out, "🚨 По аварии узла", "#e65100"), unsafe_allow_html=True)
        m4.markdown(kpi(n_esc, "⬆️ Эскалация", ACTION_COLOR[1]), unsafe_allow_html=True)

        if filt:
            table = pd.DataFrame([{
                "№": c.claim_id,
                "Заявка": c.text[:55],
                "Решение": r.action_name,
                "Источник": r.source,
                "Узел": (r.topo["pon"] if r.topo else ""),
                "Флаг": ("🚨" if r.final_kind == "outage" else ("⬆️" if r.escalate else "")),
            } for c, r in filt])
            st.dataframe(table, use_container_width=True, hide_index=True)

            labels = [f"#{c.claim_id} · {r.action_name} · {c.text[:45]}" for c, r in filt]
            sel = st.selectbox("Открыть заявку для разбора", range(len(filt)),
                               format_func=lambda i: labels[i], key="q_sel")
            c, r = filt[sel]
            render_result(c, r, key_ns=f"q{sel}")
        else:
            st.info("Нет заявок под текущие фильтры.")

    # ===================== Заявка (ручной ввод) =====================
    with tab1:
        col_form, col_res = st.columns([1, 1.35])
        with col_form:
            st.subheader("🎛️ Новая заявка")
            with st.form("manual_form"):
                text = st.text_area("Текст заявки", height=90,
                                    placeholder="Например: Собака перегрызла кабель, интернет пропал")
                c1, c2 = st.columns(2)
                with c1:
                    link_status = st.selectbox("Линк (порт)", [0, 1], format_func=lambda x: "DOWN" if x == 0 else "UP")
                    auth_status = st.selectbox("Авторизация", [0, 1], format_func=lambda x: "нет" if x == 0 else "есть")
                    pppoe_status = st.selectbox("PPPoE", [0, 1], format_func=lambda x: "нет" if x == 0 else "есть")
                    dhcp_status = st.selectbox("DHCP", [0, 1], format_func=lambda x: "нет" if x == 0 else "есть")
                    dns_status = st.selectbox("DNS", [0, 1], format_func=lambda x: "не работает" if x == 0 else "работает")
                with c2:
                    errors_crc = st.number_input("Ошибки CRC", 0, 100, 0)
                    attenuation_db = st.number_input("Затухание, dB", 0.0, 60.0, 15.0)
                    ping_gateway_ms = st.number_input("Ping до шлюза, мс", 0, 500, 20)
                    session_count = st.number_input("Переподключений", 0, 50, 0)
                    equipment_owned = st.selectbox("Оборудование наше", [0, 1], format_func=lambda x: "нет" if x == 0 else "да")
                st.subheader("📍 Данные техучёта")
                c3, c4 = st.columns(2)
                with c3:
                    street = st.selectbox("Улица", ["Ленина", "Гагарина", "Мира", "Победы", "Советская", "Кирова", "Пушкина"])
                    building = st.number_input("Дом", 1, 50, 5)
                    entrance = st.number_input("Подъезд", 0, 10, 3)
                    floor = st.number_input("Этаж", 0, 20, 4)
                with c4:
                    cable_length_m = st.number_input("Длина кабеля, м", 10, 300, 80)
                    equipment_type = st.selectbox("Тип оборудования", ["роутер", "приставка", "медиаконвертер", "ONT", "коммутатор"])
                    warranty = st.selectbox("Гарантия", [0, 1], format_func=lambda x: "нет" if x == 0 else "есть")
                    rental = st.selectbox("Аренда", [0, 1], format_func=lambda x: "нет" if x == 0 else "да")
                submitted = st.form_submit_button("🧠 Запустить конвейер", use_container_width=True)

            if submitted and text.strip():
                claim = Claim(
                    text=text, link_status=link_status, auth_status=auth_status,
                    pppoe_status=pppoe_status, dhcp_status=dhcp_status, dns_status=dns_status,
                    errors_crc=errors_crc, attenuation_db=attenuation_db,
                    ping_gateway_ms=ping_gateway_ms, session_count=session_count,
                    equipment_owned=equipment_owned, street=street, building=str(building),
                    entrance=entrance, floor=floor, cable_length_m=cable_length_m,
                    equipment_type=equipment_type, warranty=warranty, rental=rental,
                )
                try:
                    res = run_pipeline(claim)
                except RuntimeError as e:
                    st.error(f"❌ {e}. Сначала: `python -m isp_triage.cli train`")
                else:
                    st.session_state.manual_claim = claim
                    st.session_state.manual_res = res
            elif submitted and not text.strip():
                st.warning("Введите текст заявки.")

        with col_res:
            st.subheader("📋 Результат конвейера")
            if "manual_res" in st.session_state:
                render_result(st.session_state.manual_claim, st.session_state.manual_res,
                              key_ns="manual")
            else:
                st.info("Слева введите заявку и нажмите «Запустить конвейер».")

    # ===================== Поток =====================
    with tab2:
        st.subheader("📡 Живая диспетчерская (поток из Helpdesk-заглушки)")
        if "feed" not in st.session_state:
            st.session_state.feed = []
        if "feed_running" not in st.session_state:
            st.session_state.feed_running = False
        if "feed_speed" not in st.session_state:
            st.session_state.feed_speed = 1.2

        c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
        if c1.button("▶ Запустить поток", use_container_width=True):
            _ensure_data()
            topology.reset_window()
            conn = HelpdeskConnector()
            st.session_state.feed_claims = conn.fetch_claims(limit=200, with_labels=False)
            st.session_state.feed_idx = 0
            st.session_state.feed_target = 20
            st.session_state.feed_running = True
            st.session_state.feed = []
            st.rerun()
        if c2.button("⏹ Стоп", use_container_width=True):
            st.session_state.feed_running = False
        if c3.button("🗑 Очистить", use_container_width=True):
            st.session_state.feed = []
            st.session_state.feed_running = False
        c4.slider("Задержка, сек", 0.3, 3.0, key="feed_speed")

        if st.session_state.get("feed_running"):
            claims = st.session_state.get("feed_claims")
            if not claims:
                st.session_state.feed_running = False
            else:
                idx = st.session_state.feed_idx
                if idx < st.session_state.feed_target and idx < len(claims):
                    claim = claims[idx]
                    res = run_pipeline(claim)
                    st.session_state.feed.append((claim, res))
                    st.session_state.feed_idx = idx + 1
                else:
                    st.session_state.feed_running = False

        feed = st.session_state.feed
        if feed:
            counts = {a: 0 for a in ACTION_NAMES}
            n_out = 0
            for _, r in feed:
                if r.final_kind == "outage":
                    n_out += 1
                else:
                    counts[r.action] += 1
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.markdown(kpi(len(feed), "Всего"), unsafe_allow_html=True)
            k2.markdown(kpi(counts[0], "🖥️ Дистанционно", ACTION_COLOR[0]), unsafe_allow_html=True)
            k3.markdown(kpi(counts[1], "📞 Звонок", ACTION_COLOR[1]), unsafe_allow_html=True)
            k4.markdown(kpi(counts[2], "🚚 Выезд", ACTION_COLOR[2]), unsafe_allow_html=True)
            k5.markdown(kpi(n_out, "🚨 Авария узла", "#e65100"), unsafe_allow_html=True)

            s = impact.summarize([r for _, r in feed], baseline_share=0.4)
            st.markdown(
                f'<div class="money">💰 Потенциальная экономия (допущение 40%): '
                f'предотвращено ≈ <b>{s["saved_rolls"]} выездов</b> ≈ '
                f'<b>{_fmt(s["saved_hours"])} ч</b> ≈ <b>{_fmt(s["saved_rub"])} ₽</b></div>',
                unsafe_allow_html=True)

            st.subheader("📜 Лента заявок (новые сверху — нажми, чтобы развернуть)")
            for i, (claim, res) in enumerate(reversed(feed)):
                newest = (i == 0)
                flag = "🚨" if res.final_kind == "outage" else ("⬆️" if res.escalate else "")
                header = (f"{ACTION_ICON[res.action]} #{claim.claim_id} · {res.action_name} {flag}· "
                          f"{claim.text[:55]}{'…' if len(claim.text) > 55 else ''}")
                with st.expander(header, expanded=newest):
                    if res.final_kind == "outage":
                        o = res.outage
                        st.error(f"🚨 {o['text']} · узел {o.get('olt','')} / {o['id']} · "
                                 f"затронуто: {o['affected']} — эскалация на узловую бригаду.")
                    ticket_card(claim, res)
                    references_block(res)
                    st.markdown("**🔄 Как принято решение**")
                    stepper(res)
                    if res.final_kind != "outage":
                        opinion_cards(res)
        else:
            st.info("Нажмите «▶ Запустить поток», чтобы заявки начали приходить одна за другой.")

        if st.session_state.get("feed_running"):
            time.sleep(st.session_state.feed_speed)
            st.rerun()

    # ===================== Обучение =====================
    with tabL:
        st.subheader("🧠 Обучение на решениях инженера (human-in-the-loop)")
        st.caption("Каждая правка инженера — сигнал обучения. Модель можно дообучить на накопленных метках.")
        s = feedback.stats()
        m1, m2, m3 = st.columns(3)
        m1.markdown(kpi(s["total"], "Всего оценок"), unsafe_allow_html=True)
        m2.markdown(kpi(s["changed"], "Правок"), unsafe_allow_html=True)
        m3.markdown(kpi(f"{s['agreement']:.0%}", "Согласие с моделью", ACTION_COLOR[0]), unsafe_allow_html=True)

        df = feedback.recent(20)
        if not df.empty:
            st.write("**Последние оценки:**")
            st.dataframe(df[["ts", "claim_id", "predicted", "corrected", "changed", "comment"]],
                         use_container_width=True, hide_index=True)
        else:
            st.info("Оценок пока нет. Поставьте «👍/✏️/👎» на заявках во вкладке «Очередь».")

        if st.button("🔁 Дообучить модель на фидбеке"):
            _ensure_data()
            base = pd.read_csv(gen.DATA_FILE, encoding="utf-8-sig")
            lab = feedback.labeled_path()
            if os.path.exists(lab):
                fb = pd.read_csv(lab, encoding="utf-8-sig")
                combined = pd.concat([base, fb], ignore_index=True)
                n_fb = len(fb)
            else:
                combined, n_fb = base, 0
            m = clf_mod.train(combined)
            st.success(f"Дообучено на {len(combined)} примерах (включая {n_fb} из фидбека). "
                       f"Новая accuracy = {m['accuracy']:.3f}")

    # ===================== Журнал =====================
    with tabJ:
        st.subheader("📜 Журнал решений (аудит)")
        entries = audit.recent(100)
        if entries:
            st.dataframe(pd.DataFrame(entries), use_container_width=True, hide_index=True)
        else:
            st.info("Пусто. Откройте заявку в «Очереди» или запустите «Поток» — решения попадут в журнал.")

    # ===================== Качество =====================
    with tab3:
        st.subheader("✅ Качество модели")
        st.info("Метрики считаются на СИНТЕТИЧЕСКОМ датасете, поэтому близки к 1.0. "
                "Это проверка работоспособности конвейера, а не боевое качество. "
                "Реальные метрики — на выгрузке из Helpdesk с разметкой эксперта.")
        if st.button("Пересчитать метрики"):
            _ensure_data()
            df = pd.read_csv(gen.DATA_FILE, encoding="utf-8-sig")
            m = clf_mod.evaluate(df)
            if not m:
                st.error("Модель не обучена. Запустите `python -m isp_triage.cli train`.")
            else:
                a1, a2, a3, a4 = st.columns(4)
                a1.markdown(kpi(f"{m['accuracy']:.3f}", "Accuracy"), unsafe_allow_html=True)
                a2.markdown(kpi(f"{m['precision']:.3f}", "Precision"), unsafe_allow_html=True)
                a3.markdown(kpi(f"{m['recall']:.3f}", "Recall"), unsafe_allow_html=True)
                a4.markdown(kpi(f"{m['f1']:.3f}", "F1"), unsafe_allow_html=True)
                st.write("**По классам:**")
                rows = []
                for name in ("Дистанционно", "Звонок", "Выезд"):
                    r = m["report"].get(name)
                    if r:
                        rows.append({"Класс": name, "Precision": round(r["precision"], 2),
                                     "Recall": round(r["recall"], 2),
                                     "F1": round(r["f1-score"], 2),
                                     "Support": int(r["support"])})
                st.table(pd.DataFrame(rows))

    st.markdown("---")
    st.caption("⚠️ Прототип (TRL 3). Данные синтетические; интеграции Helpdesk/WOS/NMS и база знаний — "
               "заглушки; LLM активен при наличии локального ollama. Экономика — оценка на условных допущениях.")


if __name__ == "__main__":
    main()
