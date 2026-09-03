"""
İtemsatış Ücretsiz Çekiliş Otomatik Katılım Botu (Ultra Hızlı Mod)
==================================================================
- Hızlandırma Optimizasyonları:
  1. Görsel ve medya engelleme (images: 2, eager load)
  2. Tek Tarayıcı Yaşam Döngüsü (delete_all_cookies ile anında geçiş)
  3. Sıfır Scroll (Direkt DOM okuma)
  4. 1 Saniye IMAP Polling (Anında 2FA kod yakalama)
- Part Seçimi (10-10 Bölme & Geçmiş Bilgisi Gösterme)
- Otomatik IMAP ile 2FA Kod Okuma (Profil Gerektirmez!)
- Normal Başlatma (python cekilis_bot.py) -> GÖRÜNÜR MOD
- BAT Dosyası (Botu_Baslat.bat)           -> TAM SESSİZ MOD
"""

import time
import sys
import os
import re
import json
import imaplib
import email
import ctypes
from datetime import datetime, timedelta
from email.header import decode_header

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
)

if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ─── Ayarlar ───────────────────────────────────────────────
BASE_URL = "https://www.itemsatis.com"
GIVEAWAY_URL = f"{BASE_URL}/ucretsiz-cekilisler.html"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS_FILE = os.path.join(BASE_DIR, "accounts.txt")
MAIL_CONFIG_FILE = os.path.join(BASE_DIR, "mail_config.json")
HISTORY_FILE = os.path.join(BASE_DIR, "run_history.json")

WAIT_TIMEOUT = 8
MIN_PARTICIPANTS = 50

# Hızlandırılmış Mikro Gecikmeler
DELAY_BETWEEN_KEYS = 0.05
DELAY_AFTER_LOGIN = 0.3
DELAY_BETWEEN_CARDS = 0.15
DELAY_BETWEEN_ACCOUNTS = 0.3


# ─── Geçmiş Kayıt (History) Yönetimi ──────────────────────
def load_history() -> dict:
    """run_history.json dosyasını okur."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_history(part_key: str, accounts_count: int, successful: int, new_joined: int):
    """Çalıştırma sonucunu run_history.json içine kaydeder."""
    history = load_history()
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    history[part_key] = {
        "last_run": now_str,
        "accounts_count": accounts_count,
        "successful": successful,
        "new_joined": new_joined
    }
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=4)
    except Exception as e:
        log(f"  ✗ Geçmiş kaydedilemedi: {e}")


# ─── Mail Config ──────────────────────────────────────────
def load_mail_config() -> dict:
    """mail_config.json dosyasını okur."""
    try:
        with open(MAIL_CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        required = ["email", "password", "provider"]
        for key in required:
            if key not in config or not config[key].strip():
                log(f"✗ mail_config.json içinde '{key}' eksik!")
                sys.exit(1)
        return config
    except FileNotFoundError:
        log(f"✗ Mail ayar dosyası bulunamadı: {MAIL_CONFIG_FILE}")
        log("  → mail_config.json oluşturun (email, password, provider)")
        sys.exit(1)
    except json.JSONDecodeError:
        log("✗ mail_config.json dosyası geçerli JSON değil!")
        sys.exit(1)


# ─── IMAP ile Otomatik 2FA Kod Okuma ─────────────────────
IMAP_SERVERS = {
    "gmail": "imap.gmail.com",
    "outlook": "imap-mail.outlook.com",
    "hotmail": "imap-mail.outlook.com",
}

_used_codes = set()  # Kullanılmış 2FA kodlarını hafızada tutar


def fetch_verification_code(mail_config: dict, target_email: str, max_wait: int = 120) -> str | None:
    """
    Ana mail kutusundan İtemsatış doğrulama kodunu çeker (1 saniyelik ultra hızlı polling).
    """
    global _used_codes
    provider = mail_config["provider"].lower()
    imap_server = IMAP_SERVERS.get(provider)
    if not imap_server:
        log(f"  ✗ Bilinmeyen mail sağlayıcı: {provider}")
        return None

    FOLDERS = ["INBOX", "[Gmail]/Spam", "Junk"]

    start_time = time.time()
    attempt = 0

    while time.time() - start_time < max_wait:
        attempt += 1
        try:
            imap = imaplib.IMAP4_SSL(imap_server, 993)
            imap.login(mail_config["email"], mail_config["password"])

            best_mail = None
            best_age = 999999
            since_date = (datetime.now() - timedelta(days=1)).strftime("%d-%b-%Y")

            for folder in FOLDERS:
                try:
                    status, _ = imap.select(folder)
                    if status != "OK":
                        continue
                except Exception:
                    continue

                status, msg_ids = imap.search(None, f'(SINCE "{since_date}")')
                if status != "OK" or not msg_ids[0]:
                    continue

                id_list = msg_ids[0].split()
                for mid in reversed(id_list[-15:]):
                    try:
                        status, data = imap.fetch(mid, "(RFC822)")
                        if status != "OK":
                            continue
                        msg = email.message_from_bytes(data[0][1])

                        raw_subject = msg.get("Subject", "")
                        decoded_parts = decode_header(raw_subject)
                        subject = ""
                        for part, charset in decoded_parts:
                            if isinstance(part, bytes):
                                subject += part.decode(charset or "utf-8", errors="replace")
                            else:
                                subject += part

                        subject_code_match = re.search(r'\b(\d{6})\b', subject)
                        from_header = msg.get("From", "").lower()
                        to_header = msg.get("To", "").lower()
                        
                        if not subject_code_match and "itemsatis" not in from_header and "itemsatis" not in subject.lower():
                            continue

                        # Hesap Doğrulama Filtresi
                        target_lower = target_email.lower()
                        target_user = target_lower.split("@")[0]
                        is_main_account = (target_lower == mail_config["email"].lower())

                        mail_text_full = f"{from_header} {to_header} {subject}".lower()
                        
                        if not is_main_account:
                            if target_lower not in mail_text_full and target_user not in mail_text_full:
                                continue
                        else:
                            if "fw:" in subject.lower() and target_user not in from_header:
                                continue

                        # Yaşını hesapla
                        date_header = msg.get("Date", "")
                        try:
                            from email.utils import parsedate_to_datetime
                            mail_time = parsedate_to_datetime(date_header)
                            now = datetime.now(mail_time.tzinfo) if mail_time.tzinfo else datetime.now()
                            age_seconds = (now - mail_time).total_seconds()
                        except Exception:
                            age_seconds = 999999

                        if age_seconds < best_age:
                            best_age = age_seconds
                            best_mail = msg
                            if subject_code_match:
                                best_mail._cached_subject_code = subject_code_match.group(1)
                            best_mail._cached_subject = subject

                    except Exception:
                        continue

            if not best_mail:
                imap.logout()
                if attempt == 1:
                    log(f"  📬 {target_email} için onay kodu bekleniyor...")
                time.sleep(1)
                continue

            if best_age > 300:
                imap.logout()
                if attempt <= 2:
                    log(f"  📬 Yeni kod bekleniyor... (en yeni mail {int(best_age)}sn önce)")
                time.sleep(1)
                continue

            extracted_code = getattr(best_mail, '_cached_subject_code', None)
            
            if not extracted_code:
                body = ""
                if best_mail.is_multipart():
                    for part in best_mail.walk():
                        content_type = part.get_content_type()
                        if content_type in ("text/plain", "text/html"):
                            try:
                                charset = part.get_content_charset() or "utf-8"
                                body += part.get_payload(decode=True).decode(charset, errors="replace")
                            except Exception:
                                body += str(part.get_payload(decode=True))
                else:
                    try:
                        charset = best_mail.get_content_charset() or "utf-8"
                        body = best_mail.get_payload(decode=True).decode(charset, errors="replace")
                    except Exception:
                        body = str(best_mail.get_payload(decode=True))

                code_match = re.search(r'\b(\d{6})\b', body)
                if code_match:
                    extracted_code = code_match.group(1)

            if extracted_code:
                if extracted_code not in _used_codes:
                    _used_codes.add(extracted_code)
                    imap.logout()
                    return extracted_code
                else:
                    imap.logout()
                    if attempt <= 2:
                        log(f"  📬 Yeni kod bekleniyor (önceki kod: {extracted_code})...")
                    time.sleep(1)
                    continue

            imap.logout()
            time.sleep(1)

        except imaplib.IMAP4.error as e:
            log(f"  ✗ IMAP hatası: {e}")
            time.sleep(1)
        except Exception as e:
            log(f"  ✗ Mail okuma hatası: {e}")
            time.sleep(1)

    log(f"  ✗ {max_wait}sn içinde doğrulama kodu bulunamadı.")
    return None


# ─── Yardımcı Fonksiyonlar ────────────────────────────────
def set_cmd_title(text: str):
    try:
        if sys.platform.startswith("win"):
            ctypes.windll.kernel32.SetConsoleTitleW(f"İtemsatış Botu | {text}")
    except Exception:
        pass


def print_progress_bar(current: int, total: int, suffix: str = "", length: int = 25):
    percent = float(current) / max(total, 1)
    filled_length = int(length * percent)
    bar = "█" * filled_length + "░" * (length - filled_length)
    print(f"\r  |{bar}| %{percent * 100:5.1f} ({current}/{total}) {suffix}", flush=True)


def log(msg: str):
    timestamp = datetime.now().strftime("%H:%M:%S")
    try:
        print(f"[{timestamp}] {msg}", flush=True)
    except Exception:
        print(f"[{timestamp}] {msg.encode('ascii', 'replace').decode('ascii')}", flush=True)


def load_accounts(filepath: str) -> list[tuple[str, str]]:
    accounts = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                username, password = line.split(":", 1)
                accounts.append((username.strip(), password.strip()))
    except FileNotFoundError:
        log(f"✗ Hesap dosyası bulunamadı: {filepath}")
        sys.exit(1)

    if not accounts:
        log("✗ Hesap dosyasında geçerli hesap bulunamadı!")
        sys.exit(1)

    return accounts


# ─── Part Seçim Menüsü ────────────────────────────────────
def select_batch_interactive(all_accounts: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], str, str]:
    total = len(all_accounts)
    batch_size = 10
    num_parts = (total + batch_size - 1) // batch_size
    history = load_history()

    print("\n" + "=" * 62)
    print("        İTEMSATIŞ ÇEKİLİŞ BOTU (PART SEÇİMİ)")
    print("=" * 62)
    print("📊 [GEÇMİŞ ÇALIŞTIRMA BİLGİLERİ]")

    for p in range(1, num_parts + 1):
        p_key = f"part_{p}"
        start_idx = (p - 1) * batch_size + 1
        end_idx = min(p * batch_size, total)
        p_info = history.get(p_key)

        if p_info:
            last_run = p_info.get("last_run", "Bilinmiyor")
            print(f"  • Part {p} (Hesap {start_idx:2d} - {end_idx:2d}) : En son {last_run}")
        else:
            print(f"  • Part {p} (Hesap {start_idx:2d} - {end_idx:2d}) : Henüz çalıştırılmadı")

    all_info = history.get("all")
    if all_info:
        last_run = all_info.get("last_run", "Bilinmiyor")
        print(f"  • Tümü   (Hesap  1 - {total:2d}) : En son {last_run}")

    print("─" * 62)
    print("Lütfen çalıştırmak istediğiniz seçeneği belirleyin:")
    for p in range(1, num_parts + 1):
        start_idx = (p - 1) * batch_size + 1
        end_idx = min(p * batch_size, total)
        print(f"  [{p}] {p}. Part'ı Çalıştır  (Hesap {start_idx} - {end_idx})")
    
    all_opt = num_parts + 1
    print(f"  [{all_opt}] Tüm Hesapları Çalıştır (Hesap 1 - {total})")
    print("  [0] Çıkış")
    print("─" * 62)

    while True:
        try:
            choice = input(f"👉 Seçiminiz (1-{all_opt} veya 0): ").strip()
            if choice == "0":
                print("Çıkış yapılıyor...")
                sys.exit(0)
            
            choice_num = int(choice)
            if 1 <= choice_num <= num_parts:
                start_i = (choice_num - 1) * batch_size
                end_i = min(choice_num * batch_size, total)
                selected = all_accounts[start_i:end_i]
                p_key = f"part_{choice_num}"
                p_title = f"{choice_num}. Part (Hesap {start_i + 1} - {end_i})"
                return selected, p_key, p_title
            elif choice_num == all_opt:
                p_key = "all"
                p_title = f"Tüm Hesaplar (1 - {total})"
                return list(all_accounts), p_key, p_title
            else:
                print(f"  ⚠️ Lütfen 1 ile {all_opt} arasında bir sayı girin.")
        except ValueError:
            print("  ⚠️ Geçersiz giriş! Lütfen bir sayı girin.")


# ─── Chrome Driver (Görseller Engelli & Ultra Hızlı) ───────
def create_driver(headless: bool = False) -> webdriver.Chrome:
    """Görselleri engelleyerek ve eager load stratejisiyle ultra hızlı Chrome başlatır."""
    options = Options()
    options.page_load_strategy = "eager"  # DOM hazır olur olmaz devam et, resimleri bekleme

    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--remote-debugging-pipe")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
    else:
        options.add_argument("--window-size=1366,768")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

    # Görsel ve ağır içerikleri engelleme
    options.add_argument("--blink-settings=imagesEnabled=false")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)

    prefs = {
        "profile.default_content_setting_values.notifications": 2,
        "profile.default_content_setting_values.images": 2,  # 2 = Görselleri tamamen engelle
    }
    options.add_experimental_option("prefs", prefs)

    try:
        driver = webdriver.Chrome(options=options)
    except Exception:
        from webdriver_manager.chrome import ChromeDriverManager
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options,
        )

    return driver


def reset_browser_session(driver: webdriver.Chrome):
    """Tarayıcıyı kapatmadan oturum çerezlerini ve depolamayı temizler."""
    try:
        driver.delete_all_cookies()
        driver.execute_script("""
            try { window.localStorage.clear(); } catch(e){}
            try { window.sessionStorage.clear(); } catch(e){}
        """)
    except Exception:
        pass


def js_click(driver: webdriver.Chrome, element):
    driver.execute_script("arguments[0].click();", element)


# ─── Giriş İşlemleri ─────────────────────────────────────
def is_definitely_logged_in(driver: webdriver.Chrome) -> bool:
    try:
        return bool(driver.execute_script("""
            var hasUserEl = document.querySelector("a[href*='cikis'], .cikisYapBtn, .item-user, .user-text, .level-badge, .bakiyeItem") !== null;
            var hasLoginBtn = document.querySelector(".LoginButtonNotUer") !== null;
            return hasUserEl && !hasLoginBtn;
        """))
    except Exception:
        return False


def ensure_login(driver: webdriver.Chrome, username: str, password: str, mail_config: dict) -> bool:
    """Giriş yapar, robot hatası alırsa otomatik tekrar dener, 2FA kodu istenirse IMAP ile otomatik çeker."""
    for login_attempt in range(1, 3):
        driver.get(GIVEAWAY_URL)
        wait = WebDriverWait(driver, WAIT_TIMEOUT)
        time.sleep(0.6)

        if is_definitely_logged_in(driver):
            log(f"  ⚡ Oturum Hazır: {username}")
            return True

        if login_attempt == 1:
            log(f"  → Giriş yapılıyor: {username}")
        else:
            log(f"  🔄 Tekrar deneniyor (Deneme {login_attempt}/2): {username}")

        try:
            driver.execute_script("""
                var modal = document.getElementById('loginModalNew');
                if (modal) {
                    modal.classList.remove('hidden');
                    modal.style.display = 'flex';
                    modal.classList.add('fixed');
                }
            """)

            username_field = wait.until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, "#loginform2 input[name='UserName']"))
            )
            username_field.clear()
            username_field.send_keys(username)

            password_field = driver.find_element(By.CSS_SELECTOR, "#loginform2 input[name='Password']")
            password_field.clear()
            password_field.send_keys(password)

            # Görünmez Cloudflare / Captcha token'ının oluşması için kısa nefes payı
            time.sleep(0.8)

            submit_btn = driver.find_element(By.CSS_SELECTOR, "#loginform2 button[type='submit'], .loginSubmitBtn2")
            js_click(driver, submit_btn)

            start_time = time.time()
            code_entered = False
            verification_detected = False

            while time.time() - start_time < 150:
                try:
                    error_el = driver.find_element(By.CSS_SELECTOR, "#loginError")
                    if error_el.is_displayed() and error_el.text.strip():
                        err_text = error_el.text.strip()
                        if "robot" in err_text.lower() and login_attempt == 1:
                            log("  ⚠️ Robot doğrulaması uyarısı alındı, sayfa yenilenip tekrar deneniyor...")
                            time.sleep(1.2)
                            break  # 2. denemeye geç
                        else:
                            log(f"  ✗ Giriş hatası: {err_text}")
                            return False
                except (NoSuchElementException, StaleElementReferenceException):
                    pass

                try:
                    verification_modal = driver.find_element(By.CSS_SELECTOR, "#verificationLoginModal")
                    if verification_modal.is_displayed() and not code_entered:
                        if not verification_detected:
                            verification_detected = True
                            log(f"  📬 2FA kodu istendi, mail kontrol ediliyor...")

                        code = fetch_verification_code(mail_config, username, max_wait=120)
                        if code:
                            log(f"  🔑 Kod bulundu: {code}")
                            try:
                                code_inputs = driver.find_elements(
                                    By.CSS_SELECTOR,
                                    "#verificationLoginModal input:not([type='hidden'])"
                                )
                                
                                if len(code_inputs) == 1:
                                    code_input = code_inputs[0]
                                    code_input.clear()
                                    code_input.send_keys(code)
                                elif len(code_inputs) == 6:
                                    for i, char in enumerate(code[:6]):
                                        code_inputs[i].clear()
                                        code_inputs[i].send_keys(char)
                                else:
                                    driver.execute_script("""
                                        var inp = document.querySelector("#verificationLoginModal input[name='code'], #verificationLoginModal input[name='verificationCode'], #verificationLoginModal input:not([type='hidden'])");
                                        if (inp) {
                                            inp.value = arguments[0];
                                            inp.dispatchEvent(new Event('input', { bubbles: true }));
                                            inp.dispatchEvent(new Event('change', { bubbles: true }));
                                        }
                                    """, code)

                                time.sleep(0.3)
                                driver.execute_script("""
                                    var modal = document.getElementById('verificationLoginModal');
                                    if (modal) {
                                        var form = modal.querySelector('form');
                                        var submitBtn = modal.querySelector("button[type='submit'], .btn-primary, .verificationSubmitBtn, .btn-success");
                                        if (submitBtn) {
                                            submitBtn.click();
                                        } else if (form) {
                                            form.submit();
                                        }
                                    }
                                """)
                                
                                code_entered = True
                                log(f"  ✓ Kod girildi ({code}), doğrulanıyor...")
                                time.sleep(1)
                            except Exception as e:
                                log(f"  ✗ Kod girme hatası: {e}")
                                return False
                        else:
                            log(f"  ✗ Mail'den kod alınamadı.")
                            return False
                except (NoSuchElementException, StaleElementReferenceException):
                    pass

                if is_definitely_logged_in(driver):
                    log(f"  ✓ Giriş başarılı: {username}")
                    time.sleep(DELAY_AFTER_LOGIN)
                    return True

                try:
                    success_modal = driver.find_element(By.CSS_SELECTOR, "#generalSuccessModal")
                    if success_modal.is_displayed():
                        log(f"  ✓ Giriş başarılı: {username}")
                        time.sleep(0.5)
                        return True
                except (NoSuchElementException, StaleElementReferenceException):
                    pass

                time.sleep(0.4)

        except Exception as e:
            if login_attempt == 2:
                log(f"  ✗ Giriş istisnası ({username}): {e}")
                return False

    return False


# ─── Çekiliş Katılım ─────────────────────────────────────
def join_single_giveaway(driver: webdriver.Chrome, giveaway_id: str) -> tuple[bool, str]:
    script = """
        var giveawayId = arguments[0];
        var callback = arguments[arguments.length - 1];

        $.ajax({
            type: "POST",
            url: "api/joinGiveaway",
            data: "giveawayID=" + giveawayId,
            success: function(raw) {
                try {
                    var data = typeof raw === 'string' ? JSON.parse(raw) : raw;
                    if (data.success === true) {
                        callback({ status: 'success', message: 'Katıldınız!' });
                        return;
                    }
                    if (data.followNeeded && data.followUserId) {
                        $.ajax({
                            type: "POST",
                            url: "api/followUser",
                            data: "userID=" + data.followUserId,
                            success: function() {
                                $.ajax({
                                    type: "POST",
                                    url: "api/joinGiveaway",
                                    data: "giveawayID=" + giveawayId,
                                    success: function(jRaw) {
                                        var jData = typeof jRaw === 'string' ? JSON.parse(jRaw) : jRaw;
                                        if (jData.success === true) {
                                            callback({ status: 'success', message: 'Takip edildi & Katıldınız!' });
                                        } else {
                                            callback({ status: 'fail', message: jData.message || 'Başarısız' });
                                        }
                                    },
                                    error: function() { callback({ status: 'error', message: 'Katılım hatası' }); }
                                });
                            },
                            error: function() { callback({ status: 'error', message: 'Takip hatası' }); }
                        });
                        return;
                    }
                    if (data.phoneNeeded) {
                        callback({ status: 'phone_needed', message: 'Telefon onayı gerekli' });
                        return;
                    }
                    callback({ status: 'fail', message: data.message || 'Bilinmeyen durum' });
                } catch(e) { callback({ status: 'error', message: e.toString() }); }
            },
            error: function() { callback({ status: 'error', message: 'Bağlantı hatası' }); }
        });
    """
    try:
        driver.set_script_timeout(8)
        result = driver.execute_async_script(script, giveaway_id)
        status = result.get('status')
        message = result.get('message', '')

        if status == 'success':
            return True, message
        else:
            return False, message
    except Exception as e:
        return False, str(e)


def join_giveaways(driver: webdriver.Chrome) -> int:
    """Sıfır Scroll ile doğrudan DOM'dan çekilişleri toplar ve katılır."""
    driver.get(GIVEAWAY_URL)
    time.sleep(0.3)

    active_cards_data = driver.execute_script("""
        var cards = document.querySelectorAll('#draws-container .giveaway-card[data-finished="0"]');
        var results = [];
        for (var i = 0; i < cards.length; i++) {
            var card = cards[i];
            var text = card.textContent || '';
            var isEnding = text.indexOf('SONA ERECEK') !== -1 || text.indexOf('Sona Erecek') !== -1 || text.indexOf('sona erecek') !== -1;
            var isStarting = text.indexOf('BAŞLAYACAK') !== -1 || text.indexOf('Başlayacak') !== -1 || text.indexOf('başlayacak') !== -1;
            if (isEnding && !isStarting) {
                var btn = card.querySelector('.btn-cekilis');
                results.push({
                    index: i,
                    title: (card.getAttribute('data-title') || card.getAttribute('data-author') || ('Çekiliş #' + (i + 1))).trim(),
                    id: btn ? btn.getAttribute('data-id') : ''
                });
            }
        }
        return results;
    """)

    if not active_cards_data:
        log("  ℹ Aktif çekiliş bulunamadı.")
        return 0

    already_joined_count = 0
    new_joined_count = 0
    skipped_count = 0

    for item in active_cards_data:
        card_idx = item['index']
        card_title = item['title'][:32] + "..." if len(item['title']) > 32 else item['title']
        giveaway_id = item['id']

        try:
            cards = driver.find_elements(By.CSS_SELECTOR, '#draws-container .giveaway-card[data-finished="0"]')
            if card_idx >= len(cards):
                continue

            card = cards[card_idx]
            card_text = card.text

            if "KATILDINIZ" in card_text.upper() or "KATILDIN" in card_text.upper():
                already_joined_count += 1
                continue

            participant_match = re.search(r'(\d+)\s*Kat', card_text)
            if participant_match and int(participant_match.group(1)) < MIN_PARTICIPANTS:
                skipped_count += 1
                continue

            if giveaway_id:
                success, msg = join_single_giveaway(driver, giveaway_id)
                if success:
                    new_joined_count += 1
                else:
                    if "zaten" in msg.lower() or "katıldınız" in msg.lower():
                        already_joined_count += 1
                    else:
                        skipped_count += 1
            else:
                try:
                    join_btn = card.find_element(By.CSS_SELECTOR, ".btn-cekilis")
                    js_click(driver, join_btn)
                    time.sleep(0.3)
                    new_joined_count += 1
                except Exception:
                    pass

            time.sleep(DELAY_BETWEEN_CARDS)

        except Exception:
            continue

    summary_parts = []
    if already_joined_count > 0:
        summary_parts.append(f"{already_joined_count} zaten katılmış")
    if skipped_count > 0:
        summary_parts.append(f"{skipped_count} şartlı/atlandı")
    if new_joined_count > 0:
        summary_parts.append(f"🎉 {new_joined_count} YENİ KATILIM")
    else:
        summary_parts.append("0 yeni katılım")

    log(f"  → Sonuç: {', '.join(summary_parts)}")
    return new_joined_count


# ─── Ana Program ──────────────────────────────────────────
def main():
    is_headless_mode = "--headless" in sys.argv
    mode_text = "SESSİZ MOD (Arka Plan)" if is_headless_mode else "GÖRÜNÜR MOD (Tarayıcı Açık)"

    # Hesapları yükle
    all_accounts = load_accounts(ACCOUNTS_FILE)

    # Kullanıcıdan Part Seçimi Al
    accounts, part_key, part_title = select_batch_interactive(all_accounts)
    total_accounts = len(accounts)

    print("\n" + "=" * 60)
    print(f"    İTEMSATIŞ ÇEKİLİŞ BOTU ({mode_text} - ULTRA HIZLI)")
    print(f"    🎯 Çalıştırılan: {part_title} ({total_accounts} Hesap)")
    print("=" * 60)

    mail_config = load_mail_config()
    log(f"✓ Mail ayarları yüklendi: {mail_config['email']}")
    log(f"✓ {total_accounts} hesap hazırlandı (Sıralı).\n")

    total_new_joined = 0
    successful_accounts = 0
    failed_accounts = 0

    start_time = time.time()
    driver = None

    try:
        # Tek bir tarayıcı başlatılır (Hız Optimizasyonu #3)
        driver = create_driver(headless=is_headless_mode)

        for idx, (username, password) in enumerate(accounts, 1):
            set_cmd_title(f"{part_title} | [{idx}/{total_accounts}] (%{int(idx/total_accounts*100)}) | Yeni: {total_new_joined}")

            print(f"\n{'─' * 55}")
            print_progress_bar(idx, total_accounts, suffix=f"| Toplam Yeni: {total_new_joined}")
            log(f"[{idx}/{total_accounts}] {username}")

            try:
                # Önceki hesaptan kalan çerezleri temizle
                reset_browser_session(driver)

                if ensure_login(driver, username, password, mail_config):
                    successful_accounts += 1
                    joined = join_giveaways(driver)
                    total_new_joined += joined
                else:
                    failed_accounts += 1
                    log(f"  ✗ Giriş yapılamadı, sıradakine geçiliyor.")
            except Exception as ex:
                failed_accounts += 1
                log(f"  ✗ Hata ({username}): {ex}")
                # Beklenmedik bir çökme olursa tarayıcıyı yeniden canlandır
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = create_driver(headless=is_headless_mode)

            time.sleep(DELAY_BETWEEN_ACCOUNTS)

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    elapsed = int(time.time() - start_time)
    minutes, seconds = divmod(elapsed, 60)

    # Geçmişe kaydet
    save_history(part_key, total_accounts, successful_accounts, total_new_joined)

    set_cmd_title(f"Tamamlandı! {part_title} | Toplam Yeni: {total_new_joined}")

    print(f"\n{'=' * 60}")
    print(f"  ÖZET RAPOR ({part_title})")
    print(f"{'=' * 60}")
    print(f"  Toplam Hesap      : {total_accounts}")
    print(f"  Başarılı Giriş    : {successful_accounts}")
    print(f"  Başarısız Giriş   : {failed_accounts}")
    print(f"  Yeni Katılınan    : {total_new_joined} Çekiliş")
    print(f"  Toplam Süre       : {minutes} dk {seconds} sn")
    print(f"{'=' * 60}")
    print("✓ Bu çalıştırma bilgileri run_history.json dosyasına kaydedildi.\n")


if __name__ == "__main__":
    main()
