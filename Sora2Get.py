#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qiita comments -> latest 6-char code watcher
- API-first (Qiita v2), fallback to Playwright HTML scraping
- Runs continuously; when a NEW code appears:
    * macOS beep + Notification Center
    * copy to clipboard (pbcopy)
    * [OPTION] frontmost appへ ⌘V → Enter を自動送信
- Persists last seen code to avoid duplicate alerts

Setup:
  pip install requests playwright
  python -m playwright install chromium   # fallback用（APIで十分なら不要だが推奨）

Run:
  python sora_lastcode_watch.py

Env (optional):
  QIITA_COMMENTS_URL  : e.g. https://qiita.com/7mpy/items/9bf1d9bf90e583f8611d#comments
  QIITA_ITEM_ID       : e.g. 9bf1d9bf90e583f8611d  (URLから自動抽出可)
  QIITA_TOKEN         : Qiita個人アクセストークン（read_qiita）
  REQUIRE_MIN_DIGITS  : 1  # 6桁中の最小数字個数（誤検出抑制。2に上げても良い）
  POLL_SECONDS        : 2  # 監視頻度（秒）
  MAX_LOAD_MORE       : 6  # HTML fallback時の「もっと見る」クリック回数
  SORA_STATE_DIR      : .sora2_state

  AUTO_PASTE          : 1 なら新コード検知時に ⌘V→Enter を送信（既定: 0）
  PASTE_DELAY_MS      : 150  # クリップボード反映待ち
  ENTER_DELAY_MS      : 80   # ⌘V後のEnter送信までの待ち
"""

import os
import re
import time
import json
import signal
import subprocess
from pathlib import Path
from typing import Optional, List

import requests

# -------------- Config --------------
QIITA_COMMENTS_URL = os.environ.get(
    "QIITA_COMMENTS_URL",
    "https://qiita.com/7mpy/items/9bf1d9bf90e583f8611d#comments",
)
REQUIRE_MIN_DIGITS = int(os.environ.get("REQUIRE_MIN_DIGITS", "1"))
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "2"))
MAX_LOAD_MORE = int(os.environ.get("MAX_LOAD_MORE", "6"))

def derive_item_id(url: str) -> Optional[str]:
    m = re.search(r"/items/([0-9a-f]{20,})", url)
    return m.group(1) if m else None

QIITA_ITEM_ID = os.environ.get("QIITA_ITEM_ID") or derive_item_id(QIITA_COMMENTS_URL) or ""
QIITA_API = f"https://qiita.com/api/v2/items/{QIITA_ITEM_ID}/comments" if QIITA_ITEM_ID else None
QIITA_TOKEN = os.environ.get("QIITA_TOKEN", "QIITA_TOKEN_HERE").strip()  # ← トークンは必ず環境変数で

STATE_DIR = Path(os.environ.get("SORA_STATE_DIR", ".sora2_state"))
STATE_DIR.mkdir(parents=True, exist_ok=True)
LASTCODE_JSON = STATE_DIR / "last_code.json"
LOGFILE = STATE_DIR / "watch_latest.log"

CODE_RE = re.compile(r"\b[A-Z0-9]{6}\b")
STOPWORDS = {
    "CENTER","HEIGHT","BORDER","MARGIN","SHRINK","RADIUS","SELECT","COLUMN",
    "INLINE","BUTTON","ACTIVE","HIDDEN","NUMBER","NORMAL","WEBKIT",
}

def log(msg: str) -> None:
    line = msg
    print(line, flush=True)
    try:
        with LOGFILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def read_last_code() -> Optional[str]:
    if LASTCODE_JSON.exists():
        try:
            return json.loads(LASTCODE_JSON.read_text(encoding="utf-8")).get("last_code")
        except Exception:
            return None
    return None

def write_last_code(code: str) -> None:
    LASTCODE_JSON.write_text(json.dumps({"last_code": code}, ensure_ascii=False, indent=2), encoding="utf-8")

def extract_codes_from_text(text: str, min_digits: int) -> List[str]:
    up = text.upper()
    if "U003" in up or "U002" in up:
        return []
    out: List[str] = []
    for m in CODE_RE.findall(up):
        if m in STOPWORDS:
            continue
        if sum(ch.isdigit() for ch in m) >= min_digits:
            out.append(m)
    return out

def get_latest_code_from_api() -> Optional[str]:
    if not QIITA_API:
        return None
    headers = {"Accept": "application/json"}
    if QIITA_TOKEN:
        headers["Authorization"] = f"Bearer {QIITA_TOKEN}"
    try:
        r = requests.get(QIITA_API, headers=headers, params={"per_page": 100, "page": 1}, timeout=15)
        r.raise_for_status()
        data = r.json()
        for c in data:  # newest-first 想定
            for field in ("body", "rendered_body"):
                txt = c.get(field) or ""
                codes = extract_codes_from_text(txt, REQUIRE_MIN_DIGITS)
                if codes:
                    return codes[0]
    except Exception as e:
        log(f"[api] {type(e).__name__}: {e}")
    return None

# -------- HTML fallback (Playwright) --------
def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False

async def get_latest_code_from_html() -> Optional[str]:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(QIITA_COMMENTS_URL, wait_until="domcontentloaded")
        try:
            await page.wait_for_function(
                """() => !!Array.from(document.querySelectorAll('*'))
                         .find(el => /comment/i.test((el.className||'') + ' ' + (el.id||'')))""",
                timeout=15000,
            )
        except PlaywrightTimeoutError:
            pass

        # load more
        for _ in range(MAX_LOAD_MORE):
            try:
                btn = await page.query_selector('button:has-text("もっと見る"), button:has-text("Load more"), a:has-text("もっと見る"), a:has-text("Load more")')
                if not btn:
                    break
                await btn.click()
                await page.wait_for_timeout(800)
            except Exception:
                break

        # collect comment-ish blocks newest-first
        texts = await page.evaluate("""() => {
            const nodes = Array.from(document.querySelectorAll('*'));
            const buckets = [];
            for (const el of nodes) {
                const sig = (el.className || '') + ' ' + (el.id || '');
                if (/comment/i.test(sig)) {
                    const t = (el.innerText || '').trim();
                    if (t) buckets.push(t);
                }
            }
            if (buckets.length === 0) {
                const bodyText = (document.body.innerText || '').split('\\n').map(s=>s.trim()).filter(Boolean);
                return bodyText.slice(-400).reverse();
            }
            return buckets.reverse();
        }""")

        for t in texts:
            codes = extract_codes_from_text(t, REQUIRE_MIN_DIGITS)
            if codes:
                await ctx.close()
                await browser.close()
                return codes[0]

        await ctx.close()
        await browser.close()
    return None

# ---- NEW: frontmost app へ ⌘V → Enter を送る ----
def paste_and_submit() -> None:
    """前面アプリに ⌘V → Enter を送る（macOS）。Accessibility 権限が必要。"""
    import time as _time

    paste_delay = int(os.environ.get("PASTE_DELAY_MS", "150"))
    enter_delay = int(os.environ.get("ENTER_DELAY_MS", "80"))

    # ⌘V
    try:
        subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to keystroke "v" using command down'],
            check=False
        )
    except Exception:
        pass

    _time.sleep(paste_delay / 1000.0)

    # Enter (key code 36)
    try:
        subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to key code 36'],
            check=False
        )
    except Exception:
        pass

    _time.sleep(enter_delay / 1000.0)

def notify(code: str) -> None:
    import time as _time

    # ビープ & 通知
    try:
        subprocess.run(["osascript", "-e", "beep 3"], check=False)
        subprocess.run(
            ["osascript", "-e", f'display notification "{code}" with title "New Sora code"'],
            check=False
        )
    except Exception:
        pass

    # 予備のシステム音
    try:
        subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], check=False)
    except Exception:
        pass

    # クリップボードにコピー
    try:
        p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        p.communicate(input=code.encode("utf-8"))
    except Exception:
        pass

    # OPTION: いまの前面アプリに ⌘V → Enter
    try:
        if os.environ.get("AUTO_PASTE", "0") == "1":
            # ほんの少し待ってから貼り付け（フォーカス&クリップボード反映を待機）
            _time.sleep(int(os.environ.get("PASTE_DELAY_MS", "150")) / 1000.0)
            paste_and_submit()
    except Exception:
        pass


RUNNING = True
def _sigint(_sig, _frm):
    global RUNNING
    RUNNING = False
    log("Interrupted. Exiting...")

def main():
    import asyncio
    signal.signal(signal.SIGINT, _sigint)

    if not QIITA_ITEM_ID:
        log("Error: QIITA_ITEM_ID が特定できません（URLから抽出できない場合は環境変数で指定してください）。")
        return

    last = read_last_code()
    log(f"Watcher start | poll={POLL_SECONDS}s | min_digits={REQUIRE_MIN_DIGITS} | item_id={QIITA_ITEM_ID}")
    backoff = POLL_SECONDS

    while RUNNING:
        try:
            # 1) Try API
            latest = get_latest_code_from_api()

            # 2) Fallback to HTML if necessary
            if not latest and playwright_available():
                latest = asyncio.run(get_latest_code_from_html())

            if latest:
                log(f"Latest on page: {latest}")
                if latest != last:
                    log("NEW code detected -> notify & copy (and optional paste)")
                    notify(latest)
                    write_last_code(latest)
                    last = latest
                    backoff = POLL_SECONDS
                else:
                    log("Same as last seen. No action.")
            else:
                log("No codes detected (API+HTML).")

            # sleep
            for _ in range(POLL_SECONDS):
                if not RUNNING:
                    break
                time.sleep(1)

        except Exception as e:
            log(f"[loop] {type(e).__name__}: {e}")
            backoff = min(int(backoff * 2), 300)
            time.sleep(backoff)

if __name__ == "__main__":
    main()
