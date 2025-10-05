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

# --- Ayarlar (çalışan mevcut değerlerin aynısı) ---
TARGET_URL   = "https://termine-reservieren.de/termine/buergeramt.mainz/"
UNIT_TEXT    = "Abteilung Ausländerangelegenheiten"
CONCERN_TEXT = "Überträge von Aufenthaltstiteln (neuer Pass)"

WINDOW_DAYS  = int(os.getenv("WINDOW_DAYS", "12"))
STATE_FILE   = os.getenv("STATE_FILE", ".state_earliest.txt")
INTERVAL_MIN = int(os.getenv("CHECK_INTERVAL_MINUTES", "12"))

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "YourGmail@gmail.com"     # Your mail
SMTP_PASS = "YourAppCode"           # Gmail app password
MAIL_TO   = "YourGmail@gmail.com"     # Your or target mail

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

def click_by_exact_text(page, text):
    # Adı tam olarak text olan button/link'e öncelik ver
    pattern = re.compile(rf"^\s*{re.escape(text)}\s*$")

    for role in ["button", "link"]:
        try:
            el = page.get_by_role(role, name=pattern)
            if el.count() and el.first.is_visible():
                el.first.scroll_into_view_if_needed()
                page.wait_for_timeout(100)
                el.first.click()
                return True
        except Exception:
            pass

    # Son çare: metin düğümü tam eşleşme (gevşek değil!)
    try:
        el = page.get_by_text(text, exact=True)
        if el.count() and el.first.is_visible():
            el.first.scroll_into_view_if_needed()
            page.wait_for_timeout(100)
            el.first.click()
            return True
    except Exception:
        pass

    return False
def click_plus_for_label_auto(page, expected_label: str) -> bool:
    """
    Sayfadaki TÜM '+' butonlarını gezer.
    Her birinin ait olduğu satırın metnini okur;
    metinde expected_label geçiyorsa o satırın '+' butonuna tıklar.
    """
    # Tüm '+' adaylarını topla
    pluses = page.locator(
        "xpath=//button[normalize-space(.)='+'] | //*[@role='button' and normalize-space(.)='+']"
    )
    total = pluses.count()
    if total == 0:
        return False

    for i in range(total):
        btn = pluses.nth(i)

        # Bu '+' butonunun satır/kapsayıcısını bul (li/tr/div önceliği)
        container = None
        for xp in ["xpath=ancestor::li[1]", "xpath=ancestor::tr[1]", "xpath=ancestor::div[1]"]:
            try:
                cand = btn.locator(xp)
                if cand.count():
                    container = cand.first
                    break
            except Exception:
                pass
        if container is None:
            container = btn

        # Satır metnini oku ve eşleşmeyi kontrol et
        try:
            container.scroll_into_view_if_needed()
            page.wait_for_timeout(120)
            text_in_row = container.inner_text().strip()
        except Exception:
            text_in_row = ""

        # Bazı sayfalarda whitespace/çizgi farkları olabiliyor; normalize et
        norm = " ".join(text_in_row.split())
        if expected_label in norm:
            try:
                btn.scroll_into_view_if_needed()
                page.wait_for_timeout(120)
                btn.click(timeout=2000, force=True)
                return True
            except Exception:
                return False

    return False


# →→→ YENİ: “+”ları indexle ve satır metnini doğrula
def click_plus_by_index_with_check(page, index_one_based: int, expected_label: str) -> bool:
    """
    Sayfadaki TÜM '+' butonlarını yukarıdan aşağı sırala,
    index_one_based'inci olana tıkla (1 tabanlı!). Tıklamadan önce,
    aynı satır/container içinde expected_label geçtiğini doğrula.
    """
    # 1) Tüm '+' butonlarını topla (role=button veya yazısı '+')
    pluses = page.locator(
        "xpath=//button[normalize-space(.)='+'] | //*[@role='button' and normalize-space(.)='+']"
    )
    cnt = pluses.count()
    if cnt == 0:
        return False
    if index_one_based < 1 or index_one_based > cnt:
        return False

    btn = pluses.nth(index_one_based - 1)

    # 2) Aynı SATIR/KAPSAYICIYI bul (li/tr/div önceliği)
    container = None
    for xp in ["xpath=ancestor::li[1]", "xpath=ancestor::tr[1]", "xpath=ancestor::div[1]"]:
        try:
            cand = btn.locator(xp)
            if cand.count():
                container = cand.first
                break
        except Exception:
            pass
    if container is None:
        container = btn

    # 3) Satır içinde beklenen metin gerçekten var mı?
    try:
        container.scroll_into_view_if_needed()
        page.wait_for_timeout(150)
        text_in_row = container.inner_text().strip()
    except Exception:
        text_in_row = ""

    if expected_label not in text_in_row:
        log(f"[DEBUG] Beklenen etiket bulunmadı. Satır metni: {text_in_row[:200]}")
        return False

    # 4) '+' butonunu tıkla
    try:
        btn.scroll_into_view_if_needed()
        page.wait_for_timeout(120)
        btn.click(timeout=2000, force=True)
        return True
    except Exception:
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

def find_dates_anywhere(page) -> list[date] | None:
    try:
        html = page.content()
        ds = []
        for d_, m_, y_ in re.findall(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", html):
            try:
                ds.append(date(int(y_), int(m_), int(d_)))
            except:
                pass
        return sorted(set(ds)) or None
    except:
        return None

def find_next_termin_from_text(page) -> date | None:
    """'Nächster Termin ab 15.10.2025, 09:30 Uhr' metninden tarihi yakalar."""
    try:
        txt = page.inner_text("body")
    except:
        return None

    m = re.search(r"Nächster\s+Termin\s+ab\s+(\d{1,2}\.\d{1,2}\.\d{4}).*?(\d{1,2}:\d{2})\s*Uhr",
                  txt, re.IGNORECASE | re.DOTALL)
    if not m:
        m = re.search(r"Nächster\s+Termin.*?(\d{1,2}\.\d{1,2}\.\d{4})",
                      txt, re.IGNORECASE | re.DOTALL)
        if not m:
            return None
        d_, m_, y_ = map(int, m.group(1).split("."))
        return date(y_, m_, d_)

    date_str = m.group(1)
    try:
        d_, m_, y_ = map(int, date_str.split("."))
        return date(y_, m_, d_)
    except:
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
        browser = pw.chromium.launch(channel="chrome", headless=False, slow_mo=800)
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

        # --- '+': Metne göre satırı bul ve aynı satırdaki + butonunu tıkla ---
        try:
            label = "Überträge von Aufenthaltstiteln (neuer Pass)"
            node = page.locator(
                "xpath=//*[normalize-space(.)=" + repr(label) + "]"
            ).first
            container = None
            for xp in ["xpath=ancestor::li[1]", "xpath=ancestor::tr[1]", "xpath=ancestor::div[1]"]:
                cand = node.locator(xp)
                if cand.count():
                    container = cand.first
                    break
            if container is None:
                container = node

            row_text = container.inner_text().strip()
            if label not in row_text:
                raise Exception(f"Yanlış satır: {row_text[:120]}")

            plus = container.locator(
                "button:has-text('+'), "
                "[role='button']:has-text('+'), "
                "button[aria-label*='erhöh' i], button[title*='erhöh' i], "
                "button[aria-label*='erhoh' i], button[title*='erhoh' i], "
                "button:has(svg), [role='button']:has(svg)"
            )
            count = plus.count()
            if count == 0:
                raise Exception("Bu satırda '+' butonu bulunamadı")
            btn = plus.nth(count - 1)
            btn.scroll_into_view_if_needed()
            page.wait_for_timeout(200)
            btn.click(timeout=2500, force=True)
            log("[OK] '+' başarıyla tıklandı.")
        except Exception as e:
            log(f"[ERROR] '+' tıklanamadı: {e}")
            context.close()
            browser.close()
            return None, load_state()


        # --- Anliegen: yalnızca TAM eşleşme ---
        CONCERN_CANDIDATES = [
            CONCERN_TEXT,
            "Überträge von Aufenthaltstiteln (Neuer Pass)",
            "Uebertraege von Aufenthaltstiteln (neuer Pass)",
        ]

        clicked = False
        for txt in CONCERN_CANDIDATES:
            if txt and click_by_exact_text(page, txt):
                clicked = True
                break
        if not clicked:
            raise AssertionError(f"Anliegen bulunamadı (denenenler: {CONCERN_CANDIDATES})")

        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)




        # Weiter/Fortfahren
        weiter_clicked = False
        for nm in ["Weiter", "Fortfahren", "weiter", "WEITER"]:
            try:
                btn = page.get_by_role("button", name=nm)
                if btn.count() and btn.first.is_visible():
                    btn.first.click()
                    weiter_clicked = True
                    break
            except:
                pass
        if not weiter_clicked:
            try:
                link = page.get_by_role("link", name="Weiter")
                if link.count() and link.first.is_visible():
                    link.first.click()
                    weiter_clicked = True
            except:
                pass
        if not weiter_clicked:
            raise AssertionError("Weiter/Fortfahren butonu bulunamadı.")

        # Son sayfa yüklensin
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(800)

        # 1) 'Nächster Termin ab ... Uhr' metninden dene
        found = find_next_termin_from_text(page)

        # 2) Olmazsa takvim/listeden dene
        if not found:
            found = try_find_earliest_date(page)

        # 3) Yedek: tüm sayfada dd.mm.yyyy tara
        if not found:
            any_dates = find_dates_anywhere(page)
            if any_dates:
                found = any_dates[0]
                log(f"Yedek tarama ile tarih bulundu: {found}")

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

            # TEST için: pencere içinde herhangi bir tarih → mail
            if in_window and found:
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
