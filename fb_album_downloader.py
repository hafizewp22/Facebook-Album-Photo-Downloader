"""
Facebook Album Photo Downloader
--------------------------------
Mengunduh semua foto resolusi tinggi dari satu album Facebook publik.

CARA PAKAI:
1. Install dependency:
   pip install selenium requests

2. Download chromedriver yang cocok dengan versi Chrome kamu:
   https://googlechromelabs.github.io/chrome-for-testing/
   (atau install via: pip install webdriver-manager, lihat catatan di bawah)

3. Jalankan:
   python fb_album_downloader.py "https://www.facebook.com/media/set/?set=oa.XXXXXXXXXX"

4. Jendela Chrome akan terbuka. Kalau diminta login/verifikasi, login manual
   di jendela itu, lalu tekan ENTER di terminal untuk lanjut.

5. Foto akan tersimpan di folder ./downloads/<nama_album>/
"""

import os
import re
import sys
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options

# ---------- KONFIGURASI ----------
DELAY_ANTAR_FOTO = 1.5      # jeda detik antar klik "next" (perbesar kalau sering diblokir)
DELAY_LOAD_AWAL = 3         # jeda tunggu load halaman awal
MAX_RETRY = 3                # retry kalau elemen belum muncul
OUTPUT_DIR = "downloads"
# -----------------------------------


def setup_driver():
    options = Options()
    options.add_argument("--start-maximized")
    # Jangan pakai headless dulu supaya kamu bisa login manual kalau perlu
    driver = webdriver.Chrome(options=options)
    return driver


def wait_and_login(driver, album_url):
    driver.get(album_url)
    time.sleep(DELAY_LOAD_AWAL)
    print("\n>>> Kalau Facebook minta login/captcha, silakan selesaikan di jendela Chrome.")
    input(">>> Setelah album terlihat (foto-foto thumbnail muncul), tekan ENTER di sini untuk lanjut...\n")


def get_album_name(driver):
    title = driver.title or "facebook_album"
    safe = re.sub(r'[\\/*?:"<>|]', "_", title)[:80]
    return safe.strip() or "facebook_album"


def open_first_photo(driver):
    """Klik thumbnail foto pertama untuk membuka photo viewer."""
    try:
        first_photo = driver.find_element(
            By.CSS_SELECTOR, 'a[href*="/photo/"], a[href*="photo.php"]'
        )
        first_photo.click()
        time.sleep(2)
        return True
    except Exception as e:
        print(f"Gagal membuka foto pertama: {e}")
        return False


def get_current_image_url(driver):
    """Ambil src gambar resolusi tinggi yang sedang terbuka di viewer."""
    for _ in range(MAX_RETRY):
        try:
            imgs = driver.find_elements(By.CSS_SELECTOR, "img")
            # Foto resolusi tinggi biasanya elemen img terbesar di viewer,
            # dengan atribut src berisi domain scontent
            candidates = [
                img.get_attribute("src")
                for img in imgs
                if img.get_attribute("src") and "scontent" in img.get_attribute("src")
            ]
            if candidates:
                # Ambil yang paling panjang URL-nya (biasanya resolusi asli)
                return max(candidates, key=len)
        except Exception:
            pass
        time.sleep(1)
    return None


def click_next(driver):
    """Klik tombol Next (panah kanan) di photo viewer."""
    try:
        next_btn = driver.find_element(
            By.CSS_SELECTOR, 'div[aria-label="Next photo"], div[aria-label="Foto berikutnya"]'
        )
        next_btn.click()
        return True
    except Exception:
        # fallback: tombol panah kanan keyboard
        try:
            body = driver.find_element(By.TAG_NAME, "body")
            body.send_keys(Keys.ARROW_RIGHT)
            return True
        except Exception as e:
            print(f"Tidak bisa klik next: {e}")
            return False


def download_image(url, folder, index):
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        ext = ".jpg"
        if ".png" in url.split("?")[0].lower():
            ext = ".png"
        path = os.path.join(folder, f"foto_{index:04d}{ext}")
        with open(path, "wb") as f:
            f.write(resp.content)
        print(f"  [{index}] tersimpan -> {path}")
        return True
    except Exception as e:
        print(f"  [{index}] GAGAL download: {e}")
        return False


def main():
    if len(sys.argv) < 2:
        print("Pakai: python fb_album_downloader.py <URL_ALBUM>")
        sys.exit(1)

    album_url = sys.argv[1]
    driver = setup_driver()

    try:
        wait_and_login(driver, album_url)
        album_name = get_album_name(driver)
        out_folder = os.path.join(OUTPUT_DIR, album_name)
        os.makedirs(out_folder, exist_ok=True)
        print(f"\nMenyimpan ke folder: {out_folder}\n")

        if not open_first_photo(driver):
            print("Tidak berhasil membuka foto pertama. Cek URL / login.")
            return

        seen_urls = set()
        index = 1
        stagnant_count = 0

        while True:
            url = get_current_image_url(driver)
            if url and url not in seen_urls:
                seen_urls.add(url)
                download_image(url, out_folder, index)
                index += 1
                stagnant_count = 0
            else:
                stagnant_count += 1
                if stagnant_count >= 3:
                    print("\nSepertinya sudah sampai foto terakhir (URL tidak berubah). Selesai.")
                    break

            if not click_next(driver):
                print("\nTidak bisa lanjut ke foto berikutnya. Berhenti.")
                break

            time.sleep(DELAY_ANTAR_FOTO)

        print(f"\nSelesai. Total {index - 1} foto berhasil diunduh ke: {out_folder}")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()