"""
Facebook Album Photo Downloader
--------------------------------
Downloads all high-resolution photos from a single public Facebook album.

USAGE:
1. Install dependencies:
   pip install selenium requests

2. Run:
   python fb_album_downloader.py "https://www.facebook.com/media/set/?set=oa.XXXXXXXXXX"

   On the FIRST run the script imports your MAIN Chrome profile (cookies +
   logins included, caches skipped) into ./chrome_profile/ and drives a real
   Chrome window from there, so normally you don't have to log in again.
   Later runs reuse that saved profile.

   Options:
     --chrome-profile NAME        main-Chrome profile to import: directory name
                                   ("Default", "Profile 1", ...) or its display
                                   name (e.g. "Pekerjaan"). Default: "Default".
     --reimport-main-profile      re-copy the main Chrome profile into
                                   ./chrome_profile/ (overwrites it)
     --fresh-profile              start with an empty profile; logins done in
                                   the script's Chrome persist for later runs
     --debugger-address HOST:PORT attach to a Chrome you started yourself, e.g.
                                   chrome --remote-debugging-port=9222
                                         --user-data-dir=C:/chrome-debug
                                   then pass --debugger-address 127.0.0.1:9222

3. A Chrome window will open. If Facebook asks you to log in or verify,
   do it manually in that window, then press ENTER in the terminal to continue.

4. Photos will be saved to ./downloads/<album_name>/

NOTES:
- Since Chrome 136, Google blocks remote debugging (which Selenium needs) on
  the DEFAULT user data directory, so a script can no longer drive your main
  Chrome profile in place. Importing a copy of that profile is the supported
  workaround, and logins still carry over on the same machine.
- chromedriver is fetched automatically by Selenium Manager (Selenium >= 4.6);
  no manual chromedriver download is needed.
- The script resumes: photos already in the output folder are skipped when
  you rerun it after an interruption. A stuck Chrome is restarted
  automatically and the run continues where it left off.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException

# ---------- CONFIG ----------
DELAY_BETWEEN_PHOTOS = 1.5   # seconds between photos (increase if you get rate-limited)
DELAY_INITIAL_LOAD = 3       # seconds to wait for the initial page load
SCROLL_PAUSE = 1.5           # seconds between scroll steps while collecting photo links
MAX_SCROLLS = 200            # safety cap for the auto-scroll loop
PHOTO_PAGE_TIMEOUT = 15     # seconds to wait for a photo page to show its image
PAGE_LOAD_TIMEOUT = 45      # seconds a page may take to load before we move on
MAX_BROWSER_RESTARTS = 5    # how often a stuck Chrome may be restarted before giving up
OUTPUT_DIR = "downloads"

# Folder where the script keeps its own persistent copy of your Chrome profile.
AUTOMATION_PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome_profile")
PROFILE_MARKER = os.path.join(AUTOMATION_PROFILE_DIR, "fb_downloader_profile.txt")
# -----------------------------


# ---------------------------------------------------------------------------
# Main-Chrome profile handling
# ---------------------------------------------------------------------------

def find_main_chrome_user_data_dir():
    """Locate the main Google Chrome user data directory on this machine."""
    candidates = []
    env_dir = os.environ.get("CHROME_USER_DATA_DIR")  # optional manual override
    if env_dir:
        candidates.append(env_dir)
    if sys.platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA") or os.path.expandvars(
            r"%USERPROFILE%\AppData\Local")
        candidates.append(os.path.join(local, "Google", "Chrome", "User Data"))
    elif sys.platform == "darwin":
        candidates.append(os.path.expanduser("~/Library/Application Support/Google/Chrome"))
    else:
        candidates += [
            os.path.expanduser("~/.config/google-chrome"),
            os.path.expanduser("~/.config/chromium"),
        ]
    for c in candidates:
        if os.path.isfile(os.path.join(c, "Local State")):
            return os.path.normpath(c)
    return None


def list_chrome_profiles(user_data_dir):
    """Return [(directory_name, display_name), ...] for a Chrome user data dir."""
    profiles = []
    try:
        with open(os.path.join(user_data_dir, "Local State"), encoding="utf-8") as f:
            info = json.load(f).get("profile", {}).get("info_cache", {})
        for dir_name, meta in info.items():
            profiles.append((dir_name, meta.get("name") or dir_name))
    except Exception:
        pass
    if not profiles:  # fall back to plain directory names
        try:
            entries = os.listdir(user_data_dir)
        except OSError:
            entries = []
        for entry in sorted(entries):
            if re.fullmatch(r"Default|Profile \d+", entry) and os.path.isdir(
                    os.path.join(user_data_dir, entry)):
                profiles.append((entry, entry))
    profiles.sort(key=lambda p: (p[0] != "Default", p[0]))
    return profiles


def resolve_profile_dir_name(user_data_dir, wanted=None):
    """Match a user-supplied profile (dir name or display name) to a directory."""
    profiles = list_chrome_profiles(user_data_dir)
    if not profiles:
        return None
    if not wanted:
        return profiles[0][0]
    wanted_l = str(wanted).strip().lower()
    for dir_name, display in profiles:
        if wanted_l in (dir_name.lower(), display.lower()):
            return dir_name
    return None


def main_chrome_is_running():
    """Best-effort check whether Chrome is currently running (used before importing)."""
    try:
        if sys.platform.startswith("win"):
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
                capture_output=True, text=True, timeout=20,
            )
            return "chrome.exe" in (out.stdout or "").lower()
        for name in ("chrome", "google-chrome", "Google Chrome"):
            proc = subprocess.run(["pgrep", "-x", name],
                                 capture_output=True, timeout=20)
            if proc.returncode == 0:
                return True
        return False
    except Exception:
        return False


# Regenerable cache/lock junk that is pointless to copy into the automation profile.
PROFILE_SKIP_ENTRIES = {
    # caches (can be gigabytes)
    "Cache", "Cache_Data", "Code Cache", "GPUCache", "GrShaderCache", "ShaderCache",
    "GraphiteDawnCache", "DawnGraphiteCache", "DawnWebGPUCache", "Media Cache",
    "crash_cache", "OptimizationGuidePredictionModels", "shared_proto_db",
    # tied to a live browser session / not needed to stay logged in
    "Service Worker", "blob_storage", "Sync Data", "Sync Data Backup",
    "Sessions", "Session Storage", "File System", "databases",
}
PROFILE_SKIP_FILES = {"lockfile", "LOCK", "SingletonLock", "SingletonCookie", "SingletonSocket"}


def _skip_profile_entry(_directory, entries):
    return [e for e in entries
            if e in PROFILE_SKIP_ENTRIES
            or e in PROFILE_SKIP_FILES
            or e.endswith(".tmp")]


def _write_marker(profile_dir_name):
    os.makedirs(AUTOMATION_PROFILE_DIR, exist_ok=True)
    with open(PROFILE_MARKER, "w", encoding="utf-8") as f:
        f.write(profile_dir_name)


def get_dir_size_mb(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total / (1024 * 1024)


def import_main_profile(src_user_data_dir, profile_dir_name):
    """Copy the main Chrome profile (login included) into AUTOMATION_PROFILE_DIR."""
    src_profile = os.path.join(src_user_data_dir, profile_dir_name)
    print(f"Importing main Chrome profile -> {AUTOMATION_PROFILE_DIR}")
    print("  (one-time copy; caches are skipped to keep it small)")
    os.makedirs(AUTOMATION_PROFILE_DIR, exist_ok=True)
    errors = []

    try:
        shutil.copy2(os.path.join(src_user_data_dir, "Local State"),
                     os.path.join(AUTOMATION_PROFILE_DIR, "Local State"))
    except OSError as e:
        errors.append(f"Local State: {e}")

    dest_profile = os.path.join(AUTOMATION_PROFILE_DIR, profile_dir_name)
    try:
        shutil.copytree(src_profile, dest_profile, ignore=_skip_profile_entry,
                        dirs_exist_ok=True)
    except shutil.Error as e:  # copytree collects per-file errors
        for src, _dst, why in e.args[0]:
            errors.append(f"{os.path.basename(src)}: {why}")
    except OSError as e:
        errors.append(str(e))

    _write_marker(profile_dir_name)

    size_mb = get_dir_size_mb(dest_profile)
    cookies_ok = (os.path.isfile(os.path.join(dest_profile, "Network", "Cookies"))
                  or os.path.isfile(os.path.join(dest_profile, "Cookies")))
    if errors:
        print(f"  done with {len(errors)} copy error(s), e.g. {errors[0]}")
    print(f"  copied profile '{profile_dir_name}' ({size_mb:.0f} MB)")
    if cookies_ok:
        print("  cookies included - you should already be logged in")
    else:
        print("  WARNING: cookies file was not copied.")
        print("  Close ALL Chrome windows and run again with --reimport-main-profile.")
    return cookies_ok


def automation_profile_initialized():
    """True if ./chrome_profile already contains a usable profile."""
    if os.path.isfile(PROFILE_MARKER):
        return True
    if not os.path.isfile(os.path.join(AUTOMATION_PROFILE_DIR, "Local State")):
        return False
    return any(os.path.isdir(os.path.join(AUTOMATION_PROFILE_DIR, d))
               for d, _n in list_chrome_profiles(AUTOMATION_PROFILE_DIR))


def get_saved_profile_dir_name():
    """Which profile directory inside AUTOMATION_PROFILE_DIR should be used."""
    if os.path.isfile(PROFILE_MARKER):
        try:
            with open(PROFILE_MARKER, encoding="utf-8") as f:
                name = f.read().strip()
            if name and os.path.isdir(os.path.join(AUTOMATION_PROFILE_DIR, name)):
                return name
        except OSError:
            pass
    for dir_name, _n in list_chrome_profiles(AUTOMATION_PROFILE_DIR):
        if os.path.isdir(os.path.join(AUTOMATION_PROFILE_DIR, dir_name)):
            return dir_name
    return "Default"


def prepare_automation_profile(args):
    """Make sure ./chrome_profile is ready. Returns the profile directory name."""
    if args.fresh_profile:
        if os.path.isdir(AUTOMATION_PROFILE_DIR):
            shutil.rmtree(AUTOMATION_PROFILE_DIR, ignore_errors=True)
        _write_marker("Default")
        print(f"Starting with a fresh profile in {AUTOMATION_PROFILE_DIR}")
        print("(log in once in the script's Chrome window - it persists for later runs)")
        return "Default"

    if automation_profile_initialized() and not args.reimport_main_profile:
        name = get_saved_profile_dir_name()
        print(f"Reusing saved Chrome profile ({name!r}) in {AUTOMATION_PROFILE_DIR}")
        print("- you should already be logged in")
        if args.chrome_profile:
            print("(--chrome-profile only applies when importing; "
                  "add --reimport-main-profile to switch profiles)")
        return name

    # First run (or forced re-import): import from the main Chrome.
    src = find_main_chrome_user_data_dir()
    if not src:
        os.makedirs(AUTOMATION_PROFILE_DIR, exist_ok=True)
        _write_marker("Default")
        print("No main Chrome installation found - starting with an empty profile.")
        print("(log in to Facebook once in the script's Chrome window; it will be remembered)")
        return "Default"

    profiles = list_chrome_profiles(src)
    profile_dir_name = resolve_profile_dir_name(src, args.chrome_profile)
    if profile_dir_name is None:
        names = ", ".join(f"{d!r} ({n})" for d, n in profiles) or "none found"
        print(f"Profile {args.chrome_profile!r} not found in {src}")
        print(f"Available profiles: {names}")
        sys.exit(2)

    if main_chrome_is_running():
        print("NOTE: Chrome appears to be running right now.")
        print("      For a clean copy (with your Facebook login), close ALL Chrome windows first.")
        answer = input("      Continue anyway? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Cancelled. Close Chrome, then run the script again.")
            sys.exit(1)

    if os.path.isdir(AUTOMATION_PROFILE_DIR):
        print("(overwriting the previous copy in chrome_profile/)")
        shutil.rmtree(AUTOMATION_PROFILE_DIR, ignore_errors=True)

    display = dict(profiles).get(profile_dir_name, profile_dir_name)
    print(f"Using main Chrome profile: {display!r} ({profile_dir_name})")
    import_main_profile(src, profile_dir_name)
    return profile_dir_name


# ---------------------------------------------------------------------------
# Browser setup
# ---------------------------------------------------------------------------

def setup_driver(profile_dir_name="Default", debugger_address=None):
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-hang-monitor")          # no "page unresponsive" dialogs
    options.add_argument("--disable-background-networking") # less background noise on long runs
    options.add_argument("--disable-client-side-phishing-detection")
    options.add_argument("--disable-sync")
    options.add_argument("--hide-crash-restore-bubble")
    if debugger_address:
        # Attach to an already-running Chrome instead of launching one.
        options.debugger_address = debugger_address
    else:
        options.add_argument(f"--user-data-dir={AUTOMATION_PROFILE_DIR}")
        options.add_argument(f"--profile-directory={profile_dir_name}")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
    # Not using headless mode so you can log in manually if needed
    driver = webdriver.Chrome(options=options)
    # Don't wait forever on pages that never finish loading.
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
    return driver


# ---------------------------------------------------------------------------
# Browser crash/hang recovery
# ---------------------------------------------------------------------------

def _looks_like_browser_failure(e):
    """True for errors that mean the Chrome/chromedriver connection is broken."""
    if isinstance(e, TimeoutException):
        return False  # that's a page-load timeout, handled separately
    text = str(e).lower()
    return any(s in text for s in (
        "read timed out", "httpconnectionpool", "maxretryerror",
        "connection refused", "connection reset", "connection aborted",
        "session deleted", "no such window", "browser has closed",
        "target frame detached", "tab crashed", "page crashed",
    ))


def _kill_stuck_browser(driver):
    """Force-kill a hung chromedriver and the Chrome it started."""
    try:
        proc = driver.service.process
        if proc and proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except Exception:
                pass
    except Exception:
        pass
    # Chrome survives the chromedriver kill and still locks the profile,
    # so kill it too - matched via our --user-data-dir on its command line.
    marker = AUTOMATION_PROFILE_DIR
    try:
        if sys.platform.startswith("win"):
            ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
                  f"Where-Object {{ $_.CommandLine -like '*{marker}*' }} | "
                  "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, timeout=60)
        else:
            subprocess.run(["pkill", "-f", f"user-data-dir={marker}"],
                           capture_output=True, timeout=30)
    except Exception:
        pass


def restart_browser(driver, profile_dir_name, debugger_address):
    """Replace a stuck Chrome with a fresh one. Returns the new driver."""
    print("\n  >>> Chrome is stuck - restarting the browser...")
    try:
        driver.quit()
        print("  >>> Chrome closed cleanly")
    except Exception:
        print("  >>> clean close failed - force killing the stuck browser")
        _kill_stuck_browser(driver)

    last_error = None
    for attempt in (1, 2):
        try:
            time.sleep(3 if attempt == 1 else 5)
            new_driver = setup_driver(profile_dir_name, debugger_address)
            print("  >>> Chrome restarted - continuing where we left off\n")
            return new_driver
        except Exception as e:
            last_error = e
            _kill_stuck_browser(driver)
            print(f"  >>> could not start a new Chrome (attempt {attempt}): {e}")
    raise last_error


def open_photo_page(driver, url):
    """Open a photo page, tolerating pages that never finish loading."""
    try:
        driver.get(url)
    except TimeoutException:
        # Page didn't fire its load event in time - the photo is usually
        # already visible, so stop pending loads and continue.
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Facebook album scraping
# ---------------------------------------------------------------------------

def wait_and_login(driver, album_url):
    driver.get(album_url)
    time.sleep(DELAY_INITIAL_LOAD)
    print("\n>>> If Facebook asks for login/captcha, please complete it in the Chrome window.")
    input(">>> Once the album is visible (thumbnails loaded), press ENTER here to continue...\n")


def extract_album_set(album_url):
    """The 'set' identifier of an album URL, e.g. 'a.1550561427117875' from ?set=a.XXX."""
    m = re.search(r"[?&]set=([^&]+)", album_url)
    return m.group(1) if m else None


def collect_photo_links(driver, album_set=None):
    """Auto-scroll the album page and collect every unique photo URL.

    Modern Facebook lazy-loads the grid, so we scroll until no new photo
    links appear. Profile albums scroll the page body, while group/page
    albums often render the grid inside an inner scrollable <div> that
    window.scrollTo does not reach - so we scroll both. Links are filtered
    to this album's 'set' so photos from other albums / notification links
    on the same page are excluded.
    """
    def scan():
        hrefs = driver.execute_script(
            "return Array.from(document.querySelectorAll('a[href]'))"
            "  .map(a => a.href)"
            "  .filter(h => h.indexOf('fbid=') !== -1);"
        ) or []
        found = []
        for href in hrefs:
            path = href.split("?")[0]
            if "/photo/" not in path and "photo.php" not in path:
                continue  # e.g. notification links that happen to carry fbid=
            if album_set:
                m = re.search(r"[?&]set=([^&]+)", href)
                if not m or m.group(1) != album_set:
                    continue  # photo belonging to a different album on the same page
            m = re.search(r"fbid=([0-9]+)", href)
            key = m.group(1) if m else href
            found.append((key, href))
        return found

    def scroll_step():
        # Scroll the window and, for every photo link, its nearest scrollable
        # ancestor (the album grid container on group/page albums).
        return driver.execute_script("""
            window.scrollTo(0, document.body.scrollHeight);
            const seen = new Set();
            for (const a of document.querySelectorAll('a[href*="fbid="]')) {
              let el = a.parentElement;
              while (el && el !== document.body) {
                if (el.scrollHeight > el.clientHeight + 100 && el.clientHeight > 100) {
                  if (!seen.has(el)) { el.scrollTop = el.scrollHeight; seen.add(el); }
                  break;
                }
                el = el.parentElement;
              }
            }
            return seen.size;
        """)

    # Accumulate across rounds: Facebook virtualizes long grids, so links
    # scrolled out of view may disappear from the DOM again.
    collected = {}  # fbid -> href (insertion order = album order)
    stagnant_rounds = 0
    for _ in range(MAX_SCROLLS):
        scroll_step()
        time.sleep(SCROLL_PAUSE)
        before = len(collected)
        for key, href in scan():
            collected.setdefault(key, href)
        if len(collected) == before:
            stagnant_rounds += 1
            if stagnant_rounds >= 3:
                break
        else:
            stagnant_rounds = 0
            print(f"  found {len(collected)} photos so far...")
    return list(collected.values())


def get_main_image_url(driver, timeout=PHOTO_PAGE_TIMEOUT):
    """Return the src of the largest photo on a Facebook photo page.

    The photo itself is the biggest <img> pointing to a 'scontent' CDN url;
    smaller ones are avatars/icons. Uses naturalWidth/naturalHeight because
    the rendered size can be shrunk by CSS.
    """
    deadline = time.time() + timeout
    best = None  # (area, src, long_edge)
    while time.time() < deadline:
        try:
            imgs = driver.execute_script(
                "const out = [];"
                "for (const img of document.querySelectorAll('img')) {"
                "  const src = img.src || '';"
                "  if (src.indexOf('scontent') !== -1 && img.naturalWidth > 0) {"
                "    out.push({src: src, w: img.naturalWidth, h: img.naturalHeight});"
                "  }"
                "}"
                "return out;"
            ) or []
        except Exception as e:
            if _looks_like_browser_failure(e):
                raise  # browser is stuck/crashed - let the caller restart it
            imgs = []
        for img in imgs:
            area = img.get("w", 0) * img.get("h", 0)
            if area < 40000:  # skip avatars/icons (smaller than ~200x200)
                continue
            long_edge = max(img.get("w", 0), img.get("h", 0))
            if best is None or area > best[0]:
                best = (area, img["src"], long_edge)
        if best and best[2] >= 1000:
            return best[1]  # big enough - no need to wait for a higher-res swap
        time.sleep(0.5)
    return best[1] if best else None


# scontent CDN urls embed the served size, e.g.:
#   ...?stp=dst-jpg_p720x720  /  cstp=mx1365x2048&ctp=s1365x2048  /  .../s320x320/...
SIZE_TOKEN_RE = re.compile(
    r"_p(\d+)x(\d+)|_s(\d+)x(\d+)|cstp=mx(\d+)x(\d+)|ctp=s(\d+)x(\d+)|(?<![A-Za-z0-9_])s(\d+)x(\d+)/"
)
UPGRADE_PATTERNS = [
    (re.compile(r"_p\d+x\d+"), "_p2048x2048"),
    (re.compile(r"_s\d+x\d+"), "_s2048x2048"),
    (re.compile(r"cstp=mx\d+x\d+"), "cstp=mx2048x2048"),
    (re.compile(r"ctp=s\d+x\d+"), "ctp=s2048x2048"),
    (re.compile(r"(?<![A-Za-z0-9_])s\d+x\d+/"), "s2048x2048/"),
]


def _url_long_edge(url):
    """Longest image edge currently requested by an scontent url (None if unknown)."""
    m = SIZE_TOKEN_RE.search(url)
    if not m:
        return None
    nums = [int(x) for x in m.groups() if x]
    return max(nums) if nums else None


def _upgraded_url(url):
    """Same url but requesting up to 2048px, the maximum Facebook stores."""
    out = url
    for pat, repl in UPGRADE_PATTERNS:
        out = pat.sub(repl, out)
    return out


def download_image(url, folder, index, total=None):
    """Download a photo, preferring the highest-resolution variant available."""
    label = f"[{index}/{total}]" if total else f"[{index}]"
    candidates = [url]
    edge = _url_long_edge(url)
    if edge is not None and edge < 2048:
        candidates.append(_upgraded_url(url))

    best_content = None
    for u in candidates:
        try:
            resp = requests.get(u, timeout=20, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            })
            if (resp.status_code == 200
                    and resp.headers.get("content-type", "").startswith("image")):
                if best_content is None or len(resp.content) > len(best_content):
                    best_content = resp.content
        except Exception as e:
            print(f"  {label} fetch failed ({e})")

    if best_content is None:
        print(f"  {label} FAILED to download")
        return False

    ext = ".jpg"
    if ".png" in url.split("?")[0].lower():
        ext = ".png"
    path = os.path.join(folder, f"photo_{index:04d}{ext}")
    with open(path, "wb") as f:
        f.write(best_content)
    print(f"  {label} saved -> {path}")
    return True


def get_album_name(driver, album_url):
    """Folder name: '<page/user name> - <album set id>' (unique per album)."""
    page_name = ""
    try:
        h1 = driver.find_element(By.CSS_SELECTOR, "h1")
        page_name = (h1.text or "").strip()
    except Exception:
        pass

    album_set = extract_album_set(album_url)
    set_id = album_set.split(".")[-1] if album_set else ""
    if set_id:
        name = f"{page_name} - {set_id}" if page_name else f"album_{set_id}"
    else:
        title = (driver.title or "").strip() or "facebook_album"
        name = title

    safe = re.sub(r'[\\/*?:"<>|]', "_", name)[:80].strip(" .")
    return safe or "facebook_album"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Download all high-resolution photos from a public Facebook album.")
    parser.add_argument("album_url", help="URL of the Facebook album")
    parser.add_argument("--chrome-profile", metavar="NAME",
                        help="main-Chrome profile to import on the first run: "
                             "directory name ('Default', 'Profile 1', ...) or display name")
    parser.add_argument("--reimport-main-profile", action="store_true",
                        help="re-copy the main Chrome profile into ./chrome_profile "
                             "(overwrites the previous copy)")
    parser.add_argument("--fresh-profile", action="store_true",
                        help="start with an empty profile (logins persist across runs)")
    parser.add_argument("--debugger-address", metavar="HOST:PORT",
                        help="attach to a Chrome you started yourself with "
                             "--remote-debugging-port (e.g. 127.0.0.1:9222)")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.debugger_address:
        print(f"Attaching to an already-running Chrome at {args.debugger_address}")
        profile_dir_name = "Default"
    else:
        profile_dir_name = prepare_automation_profile(args)

    driver = setup_driver(profile_dir_name, args.debugger_address)

    try:
        wait_and_login(driver, args.album_url)

        # Grab the album name before auto-scrolling: Facebook virtualizes the
        # page while scrolling and drops the header (h1) from the DOM.
        album_name = get_album_name(driver, args.album_url)

        album_set = extract_album_set(args.album_url)
        photo_urls = collect_photo_links(driver, album_set)

        # Fallback: let the user scroll manually if auto-scroll found nothing
        attempts = 0
        while not photo_urls and attempts < 3:
            attempts += 1
            input(">>> No photo links found yet. In the Chrome window, scroll the album "
                  "page so the thumbnails load, then press ENTER to retry...\n")
            photo_urls = collect_photo_links(driver, album_set)

        if not photo_urls:
            print("Still no photo links found. Make sure the URL opens a Facebook "
                  "album and that you are logged in, then try again.")
            return

        out_folder = os.path.join(OUTPUT_DIR, album_name)
        os.makedirs(out_folder, exist_ok=True)

        total = len(photo_urls)
        print(f"\nAlbum: {album_name}")
        print(f"Found {total} photos. Saving to: {out_folder}")
        est_min = total * (DELAY_BETWEEN_PHOTOS + 4) / 60
        print(f"This will take roughly {est_min:.0f} minutes - you can watch the "
              "Chrome window or leave it running.\n")

        failed = []
        restarts = 0
        resumed = 0
        i = 0
        while i < total:
            idx = i + 1
            photo_url = photo_urls[i]

            # Resume: photos downloaded by an earlier (interrupted) run are skipped.
            already = any(
                os.path.isfile(os.path.join(out_folder, f"photo_{idx:04d}{ext}"))
                and os.path.getsize(os.path.join(out_folder, f"photo_{idx:04d}{ext}")) > 10240
                for ext in (".jpg", ".png")
            )
            if already:
                resumed += 1
                print(f"  [{idx}/{total}] already downloaded - skipping")
                i += 1
                continue

            try:
                open_photo_page(driver, photo_url)
                img_url = get_main_image_url(driver)
                if img_url:
                    if not download_image(img_url, out_folder, idx, total):
                        failed.append((idx, photo_url))
                else:
                    print(f"  [{idx}/{total}] no image appeared on the photo page - skipping")
                    failed.append((idx, photo_url))
                i += 1
                time.sleep(DELAY_BETWEEN_PHOTOS)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                # Browser-level error (hung/crashed Chrome): restart and retry
                # the same photo instead of failing everything after it.
                if restarts < MAX_BROWSER_RESTARTS:
                    restarts += 1
                    print(f"  [{idx}/{total}] browser error: {e}")
                    try:
                        driver = restart_browser(
                            driver, profile_dir_name, args.debugger_address)
                    except Exception as restart_error:
                        print(f"\nCould not restart Chrome: {restart_error}")
                        print("Run the script again - it will resume where "
                              "this run left off.")
                        break
                else:
                    print(f"\nChrome keeps failing after {restarts} restarts - stopping.")
                    print("Run the script again - it will resume where this "
                          "run left off.")
                    break

        print(f"\nFinished. {total - len(failed) - resumed} of {total} photos "
              f"downloaded to: {out_folder}")
        if resumed:
            print(f"({resumed} were already downloaded earlier and skipped)")
        if failed:
            print("Photos that failed (rerun the script to retry them):")
            for idx, url in failed:
                print(f"  [{idx}] {url}")

    except KeyboardInterrupt:
        print("\nInterrupted by user - photos downloaded so far are kept.")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
