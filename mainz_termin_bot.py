import os
import re
import time
import random
import locale
import smtplib
from datetime import datetime, date, timedelta
from email.message import EmailMessage
from email.utils import formatdate

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# Alman ay adları için locale (opsiyonel)
try:
    locale.setlocale(locale.LC_TIME, "de_DE.UTF-8")
except locale.Error:
    pass

# .env dosyasını yükle
# load_dotenv(encoding="utf-8-sig")

# --- Ayarlar ---
TARGET_URL   = "https://termine-reservieren.de/termine/buergeramt.mainz/"
UNIT_TEXT    = "Abteilung Ausländerangelegenheiten"
CONCERN_TEXT = "Überträge von Aufenthaltstiteln (neuer Pass)"

WINDOW_DAYS  = int(os.getenv("WINDOW_DAYS", "10"))
STATE_FILE   = os.getenv("STATE_FILE", ".state_earliest.txt")
INTERVAL_MIN = int(os.getenv("CHECK_INTERVAL_MINUTES", "12"))

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "SENINMAILADRESIN@gmail.com"     # Kendi Gmail adresin
SMTP_PASS = "GMAILAPPKODU"      # Google App Password (boşluksuz)
MAIL_TO   = "SENINMAILADRESIN6@gmail.com"     # Kendine de olabilir

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

GER_MONTHS = {
    "Januar":1,"Februar":2,"März":3,"April":4,"Mai":5,"Juni":6,
    "Juli":7,"August":8,"September":9,"Oktober":10,"November":11,"Dezember":12
}

# --- Mail gönderme ---
def send_mail(subject, body):
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and MAIL_TO):
        log("Mail ayarları eksik, gönderilemiyor.")
        return
    msg = EmailMessage()
    msg["From"] = SMTP_USER
    msg["To"] = MAIL_TO
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        log("Mail gönderildi.")
    except Exception as e:
        log(f"[MAIL ERROR] {e}")

# --- Yardımcılar ---
def log(msg: str):
    print(f"[{formatdate(localtime=True)}] {msg}", flush=True)

def load_state() -> date | None:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            s = f.read().strip()
            return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def save_state(d: date):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write(d.strftime("%Y-%m-%d"))
    except Exception:
        pass

# --- Playwright yardımcıları ---
def close_dialogs(page):
    for label in ["Schliessen","Schließen","OK","Akzeptieren","Verstanden"]:
        try:
            btn = page.get_by_role("button", name=label)
            if btn.is_visible():
                btn.click(timeout=1000)
        except Exception:
            pass

def click_by_text(page, text):
    for role in ["button", "link"]:
        try:
            el = page.get_by_role(role, name=text)
            if el.is_visible():
                el.first.click()
                return True
        except Exception:
            pass
    try:
        el = page.get_by_text(text, exact=False)
        if el.first.is_visible():
            el.first.click()
            return True
    except Exception:
        pass
    return False

def search_and_select(page, query):
    try:
        inp = page.locator("input[type='search'], input[aria-label*='Suche'], input[placeholder*='Suche']")
        if inp.is_visible():
            inp.fill(query)
            inp.press("Enter")
            page.wait_for_timeout(700)
            click_by_text(page, query)
    except Exception:
        pass

def parse_date_from_text(text: str) -> date | None:
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    if m:
        d, mth, y = map(int, m.groups())
        return date(y, mth, d)
    return None

def infer_date_from_calendar(day_text: str, heading: str) -> date | None:
    try:
        day_num = int(re.sub(r"\D+", "", day_text))
        mh = re.search(r"(Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\s+(\d{4})", heading)
        if not mh:
            return None
        month_name, year_str = mh.group(1), mh.group(2)
        month = GER_MONTHS.get(month_name)
        if not month:
            return None
        return date(int(year_str), month, day_num)
    except Exception:
        return None

def try_find_earliest_date(page) -> date | None:
    try:
        rows = page.locator("div,li,table tr").filter(has_text="Termin")
        count = min(rows.count(), 50)
        dates = []
        for i in range(count):
            txt = rows.nth(i).inner_text()
            d = parse_date_from_text(txt)
            if d:
                dates.append(d)
        if dates:
            return sorted(dates)[0]
    except Exception:
        pass

    heading = ""
    try:
        heading = page.locator("h2:has-text('Kalender'), h2:has-text('Termin'), .calendar h2").first.inner_text(timeout=1000).strip()
    except Exception:
        pass

    try:
        cells = page.locator("td,button[role='gridcell'],div[role='gridcell']").filter(has_not_text="keine")
        count = min(cells.count(), 240)
        dates = []
        for i in range(count):
            c = cells.nth(i)
            if not c.is_visible():
                continue
            txt = c.inner_text().strip()
            d = infer_date_from_calendar(txt, heading)
            if d:
                klass = (c.get_attribute("class") or "").lower()
                if "disabled" in klass:
                    continue
                dates.append(d)
        if dates:
            return sorted(dates)[0]
    except Exception:
        pass

    return None

def check_once() -> tuple[date | None, date | None]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(user_agent=UA)
        page = context.new_page()
        page.set_default_timeout(15000)

        page.goto(TARGET_URL, wait_until="domcontentloaded")
        close_dialogs(page)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(300)

        if not click_by_text(page, UNIT_TEXT):
            raise AssertionError(f"Birim bulunamadı: {UNIT_TEXT}")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(300)

        # Aynı anlamdaki farklı yazımları sırayla dene
        CONCERN_CANDIDATES = [
            CONCERN_TEXT,
            "Überträge von Aufenthaltstiteln (Neuer Pass)",
            "Überträge von Aufenthaltstiteln",
            "Uebertraege von Aufenthaltstiteln (neuer Pass)",
            "Ueberträge von Aufenthaltstiteln (neuer Pass)",  # olası encoding varyasyonu
            "Aufenthaltstitel Übertrag",
            "Aufenthaltstitel Uebertrag",
        ]

        clicked = False
        for txt in CONCERN_CANDIDATES:
            if txt and click_by_text(page, txt):
                clicked = True
                break

        if not clicked:
            # Sayfada arama kutusu varsa önce yazıp sonra tıklamayı dene
            for txt in CONCERN_CANDIDATES:
                search_and_select(page, txt)
                if click_by_text(page, txt):
                    clicked = True
                    break

        if not clicked:
            raise AssertionError(f"Anliegen bulunamadı (denenenler: {CONCERN_CANDIDATES})")

        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)

        found = try_find_earliest_date(page)

        context.close()
        browser.close()
        return found, load_state()



def main_loop():
    while True:
        try:
            found, last_known = check_once()
            today = date.today()
            window_end = today + timedelta(days=WINDOW_DAYS)

            in_window = (found is not None) and (today <= found <= window_end)
            earlier_than_last = (found is not None) and (last_known is None or found < last_known)

            log(f"found={found} last_known={last_known} in_window={in_window} earlier_than_last={earlier_than_last}")

            if in_window and earlier_than_last:
                subject = "[Mainz] Ausländerbehörde — Überträge von Aufenthaltstiteln (neuer Pass)"
                body = (
                    f"En erken uygun tarih: {found}\n\n"
                    f"{TARGET_URL}\n"
                    f"Pencere: bugün → {WINDOW_DAYS} gün"
                )
                send_mail(subject, body)
                save_state(found)

        except AssertionError as e:
            log(f"[ERROR] {e}")
        except PWTimeout:
            log("[WARN] Zaman aşımı, sonraki denemede dene.")
        except Exception as e:
            log(f"[ERROR] {e}")

        base = INTERVAL_MIN * 60
        jitter = random.randint(-120, 120)
        time.sleep(max(60, base + jitter))

if __name__ == "__main__":
    main_loop()
