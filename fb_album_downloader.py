"""
Facebook Album Photo Downloader
--------------------------------
Downloads all high-resolution photos from a single public Facebook album.

USAGE:
1. Install dependencies:
   pip install selenium requests

2. Download the chromedriver matching your Chrome version:
   https://googlechromelabs.github.io/chrome-for-testing/
   (or install via: pip install webdriver-manager)

3. Run:
   python fb_album_downloader.py "https://www.facebook.com/media/set/?set=oa.XXXXXXXXXX"

4. A Chrome window will open. If Facebook asks you to log in or verify,
   do it manually in that window, then press ENTER in the terminal to continue.

5. Photos will be saved to ./downloads/<album_name>/
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

# ---------- CONFIG ----------
DELAY_BETWEEN_PHOTOS = 1.5   # seconds between "next" clicks (increase if you get rate-limited)
DELAY_INITIAL_LOAD = 3       # seconds to wait for the initial page load
MAX_RETRY = 3                # retries when an element hasn't appeared yet
OUTPUT_DIR = "downloads"
# -----------------------------


def setup_driver():
    options = Options()
    options.add_argument("--start-maximized")
    # Not using headless mode so you can log in manually if needed
    driver = webdriver.Chrome(options=options)
    return driver


def wait_and_login(driver, album_url):
    driver.get(album_url)
    time.sleep(DELAY_INITIAL_LOAD)
    print("\n>>> If Facebook asks for login/captcha, please complete it in the Chrome window.")
    input(">>> Once the album is visible (thumbnails loaded), press ENTER here to continue...\n")


def get_album_name(driver):
    title = driver.title or "facebook_album"
    safe = re.sub(r'[\\/*?:"<>|]', "_", title)[:80]
    return safe.strip() or "facebook_album"


def open_first_photo(driver):
    """Click the first photo thumbnail to open the photo viewer."""
    try:
        first_photo = driver.find_element(
            By.CSS_SELECTOR, 'a[href*="/photo/"], a[href*="photo.php"]'
        )
        first_photo.click()
        time.sleep(2)
        return True
    except Exception as e:
        print(f"Failed to open the first photo: {e}")
        return False


def get_current_image_url(driver):
    """Get the src of the high-resolution image currently open in the viewer."""
    for _ in range(MAX_RETRY):
        try:
            imgs = driver.find_elements(By.CSS_SELECTOR, "img")
            # The high-res photo is usually the largest img element in the viewer,
            # with a src pointing to a "scontent" domain
            candidates = [
                img.get_attribute("src")
                for img in imgs
                if img.get_attribute("src") and "scontent" in img.get_attribute("src")
            ]
            if candidates:
                # Pick the longest URL (usually the original resolution)
                return max(candidates, key=len)
        except Exception:
            pass
        time.sleep(1)
    return None


def click_next(driver):
    """Click the Next (right arrow) button in the photo viewer."""
    try:
        next_btn = driver.find_element(
            By.CSS_SELECTOR, 'div[aria-label="Next photo"], div[aria-label="Foto berikutnya"]'
        )
        next_btn.click()
        return True
    except Exception:
        # fallback: right-arrow keyboard shortcut
        try:
            body = driver.find_element(By.TAG_NAME, "body")
            body.send_keys(Keys.ARROW_RIGHT)
            return True
        except Exception as e:
            print(f"Couldn't click next: {e}")
            return False


def download_image(url, folder, index):
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        ext = ".jpg"
        if ".png" in url.split("?")[0].lower():
            ext = ".png"
        path = os.path.join(folder, f"photo_{index:04d}{ext}")
        with open(path, "wb") as f:
            f.write(resp.content)
        print(f"  [{index}] saved -> {path}")
        return True
    except Exception as e:
        print(f"  [{index}] FAILED to download: {e}")
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python fb_album_downloader.py <ALBUM_URL>")
        sys.exit(1)

    album_url = sys.argv[1]
    driver = setup_driver()

    try:
        wait_and_login(driver, album_url)
        album_name = get_album_name(driver)
        out_folder = os.path.join(OUTPUT_DIR, album_name)
        os.makedirs(out_folder, exist_ok=True)
        print(f"\nSaving to folder: {out_folder}\n")

        if not open_first_photo(driver):
            print("Could not open the first photo. Check the URL / login state.")
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
                    print("\nLooks like we've reached the last photo (URL stopped changing). Done.")
                    break

            if not click_next(driver):
                print("\nCould not advance to the next photo. Stopping.")
                break

            time.sleep(DELAY_BETWEEN_PHOTOS)

        print(f"\nFinished. {index - 1} photos downloaded to: {out_folder}")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()