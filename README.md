# Facebook Album Photo Downloader

A Python + Selenium script that downloads all high-resolution photos from a single **public** Facebook album by driving a real Chrome browser (scroll, open viewer, click next, save image).

> ⚠️ **Disclaimer**: This tool automates a real browser session and is intended for downloading photos from albums you own or have explicit permission to archive (e.g. your own public page, a community album you manage). Automated scraping may violate Facebook's Terms of Service — use responsibly and at your own risk.

## Features

- Opens a Facebook album and walks through every photo in the built-in photo viewer
- Extracts the highest-resolution image URL for each photo
- Downloads images sequentially into a per-album folder
- Manual login/captcha support (you complete it in the visible Chrome window)
- Configurable delay between photos to avoid rate-limiting

## Requirements

- Python 3.8+
- Google Chrome installed
- [chromedriver](https://googlechromelabs.github.io/chrome-for-testing/) matching your Chrome version, available on your `PATH`

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

1. A Chrome window opens and loads the album URL.
2. If Facebook prompts for login or a captcha, complete it manually in that window.
3. Press **ENTER** in the terminal once the album thumbnails are visible.
4. The script opens the first photo, then automatically walks through the rest, saving each one.
5. Photos are saved to:

   ```
   downloads/<album_name>/photo_0001.jpg
   downloads/<album_name>/photo_0002.jpg
   ...
   ```

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
| `DELAY_BETWEEN_PHOTOS` | `1.5` | Seconds to wait between clicking "next" |
| `DELAY_INITIAL_LOAD` | `3` | Seconds to wait for the album page to load |
| `MAX_RETRY` | `3` | Retries when the image URL hasn't loaded yet |
| `OUTPUT_DIR` | `downloads` | Root folder for downloaded photos |

Increase `DELAY_BETWEEN_PHOTOS` if Facebook starts showing captchas or blocking requests.

## How it works

1. **Login/Load** — opens the album URL and waits for you to confirm the page is ready (and log in manually if needed).
2. **Open viewer** — clicks the first photo thumbnail to open Facebook's photo viewer.
3. **Extract image** — scans `<img>` elements for the one pointing to a `scontent` CDN URL (the actual photo, not a UI icon).
4. **Download** — saves the image via `requests` with a sequential filename.
5. **Next** — clicks the "Next photo" button (or sends the right-arrow key as a fallback) and repeats.
6. **Stop condition** — if the image URL stops changing for 3 consecutive attempts, the script assumes it has reached the last photo and stops.

## Troubleshooting

- **Nothing downloads / script exits immediately**: Facebook's page structure changes often — the CSS selectors for the first photo or "Next" button may need updating.
- **Captcha loops**: increase `DELAY_BETWEEN_PHOTOS`, or complete the captcha manually when it appears (the script pauses at login, not mid-run, so a mid-run captcha will require manual intervention).
- **chromedriver version mismatch**: make sure `chromedriver --version` matches your installed Chrome version.

## License

For personal/educational use. No warranty provided — use in accordance with Facebook's Terms of Service.