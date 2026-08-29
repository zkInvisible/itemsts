"""
İtemsatış Ücretsiz Çekiliş Otomatik Katılım (Chrome Profil Mimarisi)
===================================================================
- Her hesap için bağımsız kalıcı Chrome profili (profiles/ klasöründe) kullanır.
- Bir kez giriş yapılan hesapta oturum aylarca açık kalır (Şifre ve Mail Kodu sormaz).
- Sadece AKTİF çekilişlere (50+ katılımcı, sona erecek olanlar) katılır.
- Takip şartlarını ve katılımı sitenin API motoruyla saniyeler içinde tamamlar.
"""

import time
import sys
import os
import re
from datetime import datetime

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

# Windows konsol UTF-8 desteği
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
PROFILES_DIR = os.path.join(BASE_DIR, "profiles")

os.makedirs(PROFILES_DIR, exist_ok=True)

WAIT_TIMEOUT = 12          # Maksimum bekleme süresi (saniye)
MIN_PARTICIPANTS = 50      # 50'den az katılımcısı olan çekilişleri atla (alışveriş şartı olanlar)

# Güvenli gecikme süreleri (saniye)
DELAY_BETWEEN_KEYS = 0.25    # Form alanları arası bekleme
DELAY_AFTER_LOGIN = 1.0     # Giriş sonrası bekleme
DELAY_BETWEEN_CARDS = 0.5   # Çekilişler arası bekleme
DELAY_BETWEEN_ACCOUNTS = 1.5 # Hesaplar arası bekleme


# ─── Yardımcı Fonksiyonlar ─────────────────────────────────
def log(msg: str):
    """Zaman damgalı log mesajı yazdır."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    try:
        print(f"[{timestamp}] {msg}", flush=True)
    except Exception:
        print(f"[{timestamp}] {msg.encode('ascii', 'replace').decode('ascii')}", flush=True)


def load_accounts(filepath: str) -> list[tuple[str, str]]:
    accounts = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" not in line:
                    log(f"⚠ Satır {line_num} hatalı format (kullaniciadi:sifre olmalı): {line}")
                    continue
                username, password = line.split(":", 1)
                accounts.append((username.strip(), password.strip()))
    except FileNotFoundError:
        log(f"✗ Hesap dosyası bulunamadı: {filepath}")
        sys.exit(1)

    if not accounts:
        log("✗ Hesap dosyasında geçerli hesap bulunamadı!")
        sys.exit(1)

    log(f"✓ {len(accounts)} hesap yüklendi.")
    return accounts


def clean_profile_cache(profile_dir: str):
    """
    Profil klasöründeki gereksiz resim/video/js önbelleklerini temizler.
    Oturum dosyalarına (Cookies, LocalStorage) dokunmaz, boyutu %95 küçültür.
    """
    import shutil
    cache_folders = [
        "Default/Cache",
        "Default/Code Cache",
        "Default/GPUCache",
        "Default/DawnGraphiteCache",
        "Default/DawnWebGPUCache",
        "Default/Service Worker/CacheStorage",
        "Default/Service Worker/ScriptCache",
        "GrShaderCache",
        "ShaderCache",
        "Crashpad",
    ]
    for folder in cache_folders:
        full_path = os.path.join(profile_dir, folder.replace("/", os.sep))
        if os.path.exists(full_path):
            try:
                shutil.rmtree(full_path, ignore_errors=True)
            except Exception:
                pass


def create_driver_for_account(username: str) -> tuple[webdriver.Chrome, str]:
    """Hesaba özel hafif ve kalıcı Chrome profiliyle tarayıcıyı başlatır."""
    safe_name = re.sub(r'[^\w\-_\.]', '_', username)
    account_profile_dir = os.path.join(PROFILES_DIR, safe_name)
    os.makedirs(account_profile_dir, exist_ok=True)

    options = Options()
    options.add_argument(f"--user-data-dir={account_profile_dir}")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1366,900")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # Disk şişmesini engelleyen katı önbellek sınırları
    options.add_argument("--disk-cache-size=1048576")       # Maks 1 MB disk önbelleği
    options.add_argument("--media-cache-size=1048576")      # Maks 1 MB medya önbelleği
    options.add_argument("--disable-gpu-shader-disk-cache")
    options.add_argument("--disable-application-cache")

    prefs = {
        "profile.default_content_setting_values.notifications": 2,
        "profile.default_content_setting_values.images": 1,  # Resim yükleme standart
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
    return driver, account_profile_dir


def js_click(driver: webdriver.Chrome, element):
    driver.execute_script("arguments[0].click();", element)


def close_any_open_popups(driver: webdriver.Chrome):
    try:
        driver.execute_script("""
            if (typeof Swal !== 'undefined' && Swal.isVisible()) {
                Swal.close();
            }
            var swalContainers = document.querySelectorAll('.swal2-container');
            for (var i = 0; i < swalContainers.length; i++) {
                swalContainers[i].remove();
            }
            document.body.classList.remove('swal2-shown', 'swal2-height-auto');
        """)
    except Exception:
        pass


def is_definitely_logged_in(driver: webdriver.Chrome) -> bool:
    """Kullanıcının oturumunun açık olup olmadığını doğrular."""
    try:
        logged_in = driver.execute_script("""
            var hasUserEl = document.querySelector("a[href*='cikis'], .cikisYapBtn, .item-user, .user-text, .level-badge, .bakiyeItem") !== null;
            var hasLoginBtn = document.querySelector(".LoginButtonNotUer") !== null;
            return hasUserEl && !hasLoginBtn;
        """)
        return bool(logged_in)
    except Exception:
        return False


# ─── Giriş İşlemi ──────────────────────────────────────────
def ensure_login(driver: webdriver.Chrome, username: str, password: str) -> bool:
    """
    Oturum zaten açıksa doğrudan devam eder.
    Açık değilse otomatik giriş yapar (Gerekirse kod girilmesini bekler).
    """
    log(f"  → Oturum durumu kontrol ediliyor: {username}")
    driver.get(GIVEAWAY_URL)
    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    time.sleep(1.0)

    # 1. Profilde Oturum Zaten Açık mı?
    if is_definitely_logged_in(driver):
        log(f"  ⚡ Profilde oturum zaten açık (Şifresiz devam ediliyor): {username}")
        return True

    # 2. Açık değilse İlk Kez Giriş Yap
    log(f"  → Giriş yapılıyor: {username}")
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
        time.sleep(DELAY_BETWEEN_KEYS)

        password_field = driver.find_element(By.CSS_SELECTOR, "#loginform2 input[name='Password']")
        password_field.clear()
        password_field.send_keys(password)
        time.sleep(DELAY_BETWEEN_KEYS)

        submit_btn = driver.find_element(By.CSS_SELECTOR, "#loginform2 button[type='submit'], .loginSubmitBtn2")
        js_click(driver, submit_btn)

        log("  ⏳ Giriş bekleniyor... (Mail/SMS onayı isterse tarayıcıdan onaylayın)")

        start_time = time.time()
        last_log = ""
        while time.time() - start_time < 90:  # Kullanıcının kod girmesi için 90 sn tolerans
            # Hata kontrolü
            try:
                error_el = driver.find_element(By.CSS_SELECTOR, "#loginError")
                if error_el.is_displayed() and error_el.text.strip():
                    log(f"  ✗ Giriş hatası: {error_el.text.strip()}")
                    return False
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            # 2FA kontrolü
            try:
                verification_modal = driver.find_element(By.CSS_SELECTOR, "#verificationLoginModal")
                if verification_modal.is_displayed():
                    if last_log != "2fa":
                        log("  📬 [BEKLENİYOR] Ekranda doğrulama kodu istendi. Lütfen kodu girip onaylayın...")
                        last_log = "2fa"
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            # Giriş başarılı kontrolü
            if is_definitely_logged_in(driver):
                log(f"  ✓ Giriş başarılı ve profile kaydedildi: {username}")
                time.sleep(DELAY_AFTER_LOGIN)
                return True

            try:
                success_modal = driver.find_element(By.CSS_SELECTOR, "#generalSuccessModal")
                if success_modal.is_displayed():
                    log(f"  ✓ Giriş başarılı: {username}")
                    time.sleep(1.5)
                    return True
            except (NoSuchElementException, StaleElementReferenceException):
                pass

            time.sleep(1.0)

        log(f"  ✗ Giriş zaman aşımı: {username}")
        return False

    except Exception as e:
        log(f"  ✗ Giriş istisnası ({username}): {e}")
        return False


# ─── Çekiliş Katılım İşlemleri (Hibrit API) ────────────────
def join_single_giveaway(driver: webdriver.Chrome, giveaway_id: str) -> bool:
    """Doğrudan sitenin API motoruyla katılım sağlar."""
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
                        callback({ status: 'success', message: 'Çekilişe başarıyla katıldınız!' });
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
                                            callback({ status: 'success', message: 'Takip edildi ve çekilişe katıldınız!' });
                                        } else {
                                            callback({ status: 'fail', message: jData.message || 'Katılım başarısız' });
                                        }
                                    },
                                    error: function() {
                                        callback({ status: 'error', message: 'İkinci katılım isteği hatası' });
                                    }
                                });
                            },
                            error: function() {
                                callback({ status: 'error', message: 'Takip isteği hatası' });
                            }
                        });
                        return;
                    }
                    if (data.phoneNeeded) {
                        callback({ status: 'phone_needed', message: 'Telefon doğrulaması gerekli' });
                        return;
                    }
                    callback({ status: 'fail', message: data.message || 'Bilinmeyen durum' });
                } catch(e) {
                    callback({ status: 'error', message: e.toString() });
                }
            },
            error: function() {
                callback({ status: 'error', message: 'Sunucu bağlantı hatası' });
            }
        });
    """

    try:
        driver.set_script_timeout(10)
        result = driver.execute_async_script(script, giveaway_id)

        status = result.get('status')
        message = result.get('message', '')

        if status == 'success':
            log(f"      ✓ {message}")
            return True
        elif status == 'phone_needed':
            log(f"      ⚠ {message} (Atlandı)")
            return False
        else:
            if "zaten" in message.lower() or "katıldınız" in message.lower() or "katildiniz" in message.lower():
                log(f"      ✓ Zaten katılım sağlanmış.")
                return True
            log(f"      ℹ Sonuç: {message}")
            return False

    except Exception as e:
        log(f"      ⚠ Katılım isteği hatası: {e}")
        return False


def join_giveaways(driver: webdriver.Chrome) -> int:
    """Çekilişler sayfasındaki tüm AKTİF ve uygun çekilişlere katılır."""
    log("  → Çekilişler sayfasına gidiliyor...")
    driver.get(GIVEAWAY_URL)

    wait = WebDriverWait(driver, WAIT_TIMEOUT)
    wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
    time.sleep(0.8)

    for _ in range(4):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(0.3)
    driver.execute_script("window.scrollTo(0, 0);")
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
                    title: card.getAttribute('data-title') || card.getAttribute('data-author') || ('Çekiliş #' + (i + 1)),
                    id: btn ? btn.getAttribute('data-id') : ''
                });
            }
        }
        return results;
    """)

    if not active_cards_data:
        log("  ⚠ Aktif çekiliş bulunamadı.")
        return 0

    log(f"  → {len(active_cards_data)} aktif çekiliş inceleniyor...")
    joined_count = 0

    for item in active_cards_data:
        card_idx = item['index']
        card_title = item['title']
        giveaway_id = item['id']

        try:
            close_any_open_popups(driver)

            cards = driver.find_elements(By.CSS_SELECTOR, '#draws-container .giveaway-card[data-finished="0"]')
            if card_idx >= len(cards):
                continue

            card = cards[card_idx]
            card_text = card.text

            # 1. Zaten katılınmış mı?
            if "KATILDINIZ" in card_text.upper() or "KATILDIN" in card_text.upper():
                log(f"    [{card_idx + 1}] ✓ Zaten katılınmış: {card_title}")
                continue

            # 2. Katılımcı sayısı filtresi
            participant_match = re.search(r'(\d+)\s*Kat', card_text)
            if participant_match:
                participant_count = int(participant_match.group(1))
                if participant_count < MIN_PARTICIPANTS:
                    log(f"    [{card_idx + 1}] ⏭ Az katılımcı ({participant_count} < {MIN_PARTICIPANTS}), atlanıyor: {card_title}")
                    continue

            log(f"    [{card_idx + 1}] → Katılım yapılıyor: {card_title}")

            # 3. Katılım isteği
            if giveaway_id:
                if join_single_giveaway(driver, giveaway_id):
                    joined_count += 1
            else:
                try:
                    join_btn = card.find_element(By.CSS_SELECTOR, ".btn-cekilis")
                    js_click(driver, join_btn)
                    time.sleep(1.0)
                    joined_count += 1
                except Exception:
                    pass

            time.sleep(DELAY_BETWEEN_CARDS)

        except StaleElementReferenceException:
            continue
        except Exception as e:
            log(f"    [{card_idx + 1}] ⚠ Hata: {e}")
            close_any_open_popups(driver)
            continue

    return joined_count


# ─── Ana Çalıştırıcı ───────────────────────────────────────
def main():
    print("=" * 60)
    print("  İtemsatış Ücretsiz Çekiliş Botu (Kalıcı Profil Modu)")
    print("=" * 60)
    print("  - Her hesap için kalıcı profil klasörü kullanılır.")
    print("  - Bir kez giriş yapılan hesaplarda oturum sürekli açık kalır.")
    print("=" * 60)
    print()

    accounts = load_accounts(ACCOUNTS_FILE)
    print()

    total_joined = 0
    successful_accounts = 0
    failed_accounts = 0

    try:
        for idx, (username, password) in enumerate(accounts, 1):
            print(f"\n{'═' * 55}")
            log(f"Hesap [{idx}/{len(accounts)}]: {username}")
            print(f"{'═' * 55}")

            # Her hesap kendi izole kalıcı Chrome profiliyle açılır
            driver, profile_dir = create_driver_for_account(username)

            try:
                if ensure_login(driver, username, password):
                    successful_accounts += 1
                    joined = join_giveaways(driver)
                    total_joined += joined
                    log(f"  → Bu hesapla {joined} çekilişe işlem yapıldı.")
                else:
                    failed_accounts += 1
                    log(f"  ✗ Giriş yapılamadı, sıradaki hesaba geçiliyor.")
            finally:
                # Tarayıcıyı kapat ve ardından gereksiz önbellekleri silip boyutu küçült
                try:
                    driver.quit()
                except Exception:
                    pass
                time.sleep(0.3)
                clean_profile_cache(profile_dir)

            time.sleep(DELAY_BETWEEN_ACCOUNTS)

    except KeyboardInterrupt:
        log("\n⚠ Kullanıcı tarafından durduruldu.")
    except Exception as e:
        log(f"\n✗ Beklenmeyen hata: {e}")

    print(f"\n{'=' * 60}")
    print("  ÖZET")
    print(f"{'=' * 60}")
    print(f"  Toplam hesap      : {len(accounts)}")
    print(f"  Başarılı giriş    : {successful_accounts}")
    print(f"  Başarısız giriş   : {failed_accounts}")
    print(f"  Toplam katılım    : {total_joined}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
