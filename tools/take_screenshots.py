# -*- coding: utf-8 -*-
"""Скриншоты публичного демо (Streamlit на :8503) через Selenium."""
import os
import sys
import time
import urllib.request

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "screenshots")
os.makedirs(OUT, exist_ok=True)
URL = "http://localhost:8503"


def wait_app(driver, timeout=60):
    WebDriverWait(driver, timeout).until(
        lambda d: d.find_elements(By.CSS_SELECTOR, "[role=tab]"))


def click_tab(driver, name_part):
    tabs = driver.find_elements(By.CSS_SELECTOR, "[role=tab]")
    for t in tabs:
        if name_part in t.text:
            driver.execute_script("arguments[0].click();", t)
            return True
    return False


def click_button(driver, text_part, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        for b in driver.find_elements(By.CSS_SELECTOR, "button, .stButton"):
            if text_part in b.text:
                try:
                    driver.execute_script("arguments[0].click();", b)
                    return True
                except Exception:
                    pass
        time.sleep(0.7)
    return False


def shot(driver, name, scroll=0):
    driver.execute_script(f"window.scrollTo(0, {scroll});")
    time.sleep(0.6)
    driver.save_screenshot(os.path.join(OUT, name))
    print("saved", name)


def main():
    # ждём подъёма сервера
    for _ in range(60):
        try:
            urllib.request.urlopen(URL + "/_stcore/health", timeout=2)
            break
        except Exception:
            time.sleep(1)
    else:
        print("server not up"); sys.exit(1)

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1600,1200")
    opts.add_argument("--force-device-scale-factor=1")
    opts.add_argument("--hide-scrollbars")
    driver = webdriver.Chrome(options=opts)
    try:
        driver.get(URL)
        wait_app(driver)
        time.sleep(2.5)

        # 1) Обзор + симуляция эффекта
        click_button(driver, "Смоделировать 50 заявок", timeout=20)
        time.sleep(4)
        shot(driver, "01_overview.png", scroll=0)

        # 2) Очередь (helpdesk-style) — карточка разбора
        click_tab(driver, "Очередь")
        time.sleep(6)
        shot(driver, "02_queue.png", scroll=0)
        driver.execute_script("window.scrollTo(0, 700);")
        time.sleep(1)
        shot(driver, "03_queue_card.png", scroll=700)

        # 3) Поток — живая лента
        click_tab(driver, "Поток")
        time.sleep(2)
        click_button(driver, "Запустить поток", timeout=15)
        time.sleep(10)
        click_button(driver, "Стоп", timeout=5)
        time.sleep(1)
        shot(driver, "04_stream.png", scroll=0)

        # 4) Качество — метрики
        click_tab(driver, "Качество")
        time.sleep(1.5)
        click_button(driver, "Пересчитать метрики", timeout=15)
        time.sleep(4)
        shot(driver, "05_quality.png", scroll=0)

        print("OK")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
