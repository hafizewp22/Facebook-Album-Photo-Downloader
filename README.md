# Facebook Album Photo Downloader

A Python + Selenium script that downloads all high-resolution photos from a single **public** Facebook album by driving a real Chrome browser (scroll, open viewer, click next, save image).

> ⚠️ **Disclaimer**: This tool automates a real browser session and is intended for downloading photos from albums you own or have explicit permission to archive (e.g. your own public page, a community album you manage). Automated scraping may violate Facebook's Terms of Service — use responsibly and at your own risk.

## Features

- Opens a Facebook album, auto-scrolls to load every photo, then downloads them one by one — works for **profile, page, and group albums**
- Extracts the highest-resolution image URL for each photo (up to 2048px, Facebook's maximum)
- Downloads images sequentially into a per-album folder
- **Uses your main Chrome profile** — your existing Facebook login is imported, so you usually don't have to log in at all (see below)
- Manual login/captcha support (you complete it in the visible Chrome window)
- Configurable delay between photos to avoid rate-limiting

## Requirements

- Python 3.8+
- Google Chrome installed
- Selenium >= 4.6 (chromedriver is downloaded automatically by Selenium Manager — no manual chromedriver install needed)

## Installation

```bash
git clone https://github.com/hafizewp22/Facebook-Album-Photo-Downloader.git
cd Facebook-Album-Photo-Downloader
pip install -r requirements.txt
```

Or install dependencies directly:

```bash
pip install selenium requests
```

## Usage

```bash
python fb_album_downloader.py "https://www.facebook.com/media/set/?set=oa.XXXXXXXXXX"
```

1. **First run:** the script imports your main Chrome profile (cookies and logins, caches skipped) into a local folder `chrome_profile/`. It asks you to close any running Chrome windows first so the copy includes your login.
2. A Chrome window opens and loads the album URL — usually already logged in with your account.
3. If Facebook prompts for login or a captcha anyway, complete it manually in that window (the login is remembered for future runs).
4. Press **ENTER** in the terminal once the album thumbnails are visible.
4. The script auto-scrolls the album to load **every** photo, reports how many it found, then downloads them one by one (a big album of ~600 photos takes roughly an hour — you can stop anytime with **Ctrl+C** and keep what's already downloaded).
5. Photos are saved to:

   ```text
   downloads/<album_name>/photo_0001.jpg
   downloads/<album_name>/photo_0002.jpg
   ...
   ```

### Using your main Chrome profile

Since Chrome 136, Google blocks remote debugging (which Selenium needs) on the *default* user data directory, so no script can drive your main Chrome profile in place anymore. Instead, this tool:

- copies your main Chrome profile into `chrome_profile/` once (your Facebook login carries over on the same machine),
- reuses that saved profile on every later run, and
- keeps any new logins you do inside the script's Chrome window.

If you use several Chrome profiles, pick which one to import:

```bash
python fb_album_downloader.py "<ALBUM_URL>" --chrome-profile "Hafiz"        # by display name
python fb_album_downloader.py "<ALBUM_URL>" --chrome-profile "Profile 1"   # by directory name
```

Other profile-related options:

| Option | Description |
|---|---|
| `--chrome-profile NAME` | Which main-Chrome profile to import (display name or directory name). Default: `Default`. |
| `--reimport-main-profile` | Re-copy the main Chrome profile into `chrome_profile/` (overwrites the previous copy). |
| `--fresh-profile` | Start with an empty profile; logins done in the script's Chrome persist for later runs. |
| `--debugger-address HOST:PORT` | Advanced: attach to a Chrome you started yourself, e.g. `chrome --remote-debugging-port=9222 --user-data-dir=C:/chrome-debug`, then pass `127.0.0.1:9222`. |

You can also point the script at a custom Chrome location by setting the `CHROME_USER_DATA_DIR` environment variable.

### Downloading multiple albums

Run the script once per album URL:

```bash
python fb_album_downloader.py "https://www.facebook.com/media/set/?set=oa.1786918818993493"
python fb_album_downloader.py "https://www.facebook.com/media/set/?set=oa.1747769539988523"
python fb_album_downloader.py "https://www.facebook.com/media/set/?set=oa.2070533660201395"
```

## Configuration

Edit the constants at the top of `fb_album_downloader.py`:

| Variable | Default | Description |
|---|---|---|
| `DELAY_BETWEEN_PHOTOS` | `1.5` | Seconds to wait between photos |
| `DELAY_INITIAL_LOAD` | `3` | Seconds to wait for the album page to load |
| `SCROLL_PAUSE` | `1.5` | Seconds between scroll steps while collecting photo links |
| `MAX_SCROLLS` | `200` | Safety cap for the auto-scroll loop |
| `PHOTO_PAGE_TIMEOUT` | `15` | Seconds to wait for a photo page to show its image |
| `PAGE_LOAD_TIMEOUT` | `45` | Seconds a page may take to load before moving on |
| `MAX_BROWSER_RESTARTS` | `5` | How often a stuck Chrome may be auto-restarted before giving up |
| `OUTPUT_DIR` | `downloads` | Root folder for downloaded photos |

Increase `DELAY_BETWEEN_PHOTOS` if Facebook starts showing captchas or blocking requests.

## How it works

1. **Login/Load** — opens the album URL and waits for you to confirm the page is ready (and log in manually if needed).
2. **Collect photos** — auto-scrolls the album grid until Facebook stops loading new thumbnails, gathering every unique photo link (`/photo/?fbid=…`) that belongs to that album. Profile albums scroll the page itself, while group/page albums render the grid inside an inner scrollable panel — the script scrolls both. Facebook lazy-loads albums, so this step takes a while on big albums (e.g. ~1 min for ~600 photos).
3. **Per photo** — opens each photo's own page and picks the largest `scontent` image by real pixel dimensions (so avatars and UI icons are ignored).
4. **Max resolution** — if the served image is smaller than 2048px, the CDN URL is rewritten to request the largest stored version; whichever download is bigger is kept.
5. **Download** — saves each image as `photo_0001.jpg`, `photo_0002.jpg`, … in album order, and lists any photo that failed so you can simply rerun the script.

## Troubleshooting

- **Nothing downloads / script exits immediately**: Facebook's page structure changes often — the selectors used to find photo links and images may need updating.
- **`Read timed out` / browser error mid-run**: a hung or crashed Chrome page. The script detects this, restarts Chrome automatically, and retries the current photo — no action needed. Photos already downloaded are skipped when you rerun the script, so an interrupted run simply continues where it stopped.
- **Captcha loops / blocked mid-run**: increase `DELAY_BETWEEN_PHOTOS`, or complete the captcha manually when it appears (the script pauses at login, not mid-run, so a mid-run captcha will require manual intervention).
- **`DevToolsActivePort file doesn't exist` / session not created**: the profile folder is locked or points at Chrome's *default* user data directory. Make sure `chrome_profile/` is used (it is, by default), close all other Chrome windows using it, and retry. Only one run can use the saved profile at a time.
- **Not logged in after the first-run import**: close **all** Chrome windows (including background ones in the system tray), then run once with `--reimport-main-profile` so the cookies get copied cleanly.
- **chromedriver version mismatch**: with Selenium >= 4.6 this is handled automatically by Selenium Manager; otherwise install [chromedriver](https://googlechromelabs.github.io/chrome-for-testing/) matching your Chrome version on your `PATH`.

## License

For personal/educational use. No warranty provided — use in accordance with Facebook's Terms of Service.