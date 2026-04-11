#!/usr/bin/env python3
"""
Overview generation using Playwright browser automation.

Login strategy
--------------
Google OAuth blocks headless/automated logins. Instead we use a
**persistent browser profile** approach:

  1. `axiv login` — opens a VISIBLE browser, lets the user log in
     manually (Google OAuth, 2FA, whatever), then saves the session
     to disk.  Only needs to run once per machine / workspace.

  2. `axiv research link` — opens a HEADLESS browser reusing the saved
     session, navigates to each paper's overview page, clicks the
     "Generate" button, and polls the API until the overview is ready.
     Never touches the login flow at all.
"""

import logging
import time
from pathlib import Path
from typing import Optional, Tuple

from alphaxiv_cli.config import ALPHAXIV_WEB_URL

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


# ---------------------------------------------------------------------------
# Browser profile helpers
# ---------------------------------------------------------------------------

def _get_browser_profile() -> Path:
    """Return (and create) the workspace-local browser profile directory."""
    import os
    from alphaxiv_cli.context import get_context
    profile = get_context().root / "browser-profile"
    profile.mkdir(parents=True, exist_ok=True)
    try:
        if os.stat(profile).st_mode & 0o077:
            os.chmod(profile, 0o700)
    except OSError:
        pass
    return profile


def _launch_context(playwright, headless: bool = True):
    """Launch a persistent Chromium context using the saved profile."""
    profile = _get_browser_profile()
    return playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile),
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
        slow_mo=50,
    )


# ---------------------------------------------------------------------------
# Session check
# ---------------------------------------------------------------------------

def check_login(page: "Page") -> bool:
    """Return True if the saved session is still valid (no sign-in link visible)."""
    try:
        page.goto(f"{ALPHAXIV_WEB_URL}/", wait_until="load", timeout=20000)
        page.wait_for_timeout(1500)
        return not page.locator("a[href='/signin']").first.is_visible()
    except Exception as e:
        logger.debug(f"check_login error: {e}")
        return False


def is_session_valid() -> bool:
    """Quick check (no visible window) whether the saved session is still active."""
    if not PLAYWRIGHT_AVAILABLE:
        return False
    try:
        with sync_playwright() as pw:
            ctx = _launch_context(pw, headless=True)
            page = ctx.new_page()
            result = check_login(page)
            ctx.close()
            return result
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Manual login (called by `axiv login`)
# ---------------------------------------------------------------------------

def interactive_login() -> bool:
    """
    Open a visible browser at alphaxiv.org/signin.
    The user completes login manually (Google OAuth, 2FA, etc.).
    When they press Enter in the terminal the session is verified and saved.
    """
    if not PLAYWRIGHT_AVAILABLE:
        print("Playwright not installed.  Run:")
        print("  pip install playwright && playwright install chromium")
        return False

    print("Opening browser — log in to alphaxiv.org in the window that appears.")
    print("Come back here and press Enter once you are logged in.\n")

    try:
        with sync_playwright() as pw:
            ctx = _launch_context(pw, headless=False)
            page = ctx.new_page()
            page.goto(f"{ALPHAXIV_WEB_URL}/signin", wait_until="load", timeout=30000)

            # Hand control to the user
            input("Press Enter after you have finished logging in… ")

            # Verify: navigate to home and check we're logged in
            try:
                page.goto(f"{ALPHAXIV_WEB_URL}/", wait_until="load", timeout=15000)
                page.wait_for_timeout(1500)
                signed_in = not page.locator("a[href='/signin']").first.is_visible()
            except Exception:
                signed_in = False

            ctx.close()

            if signed_in:
                print("✓ Login verified — session saved to browser profile.")
                return True
            else:
                print("⚠ Could not verify login. Did you complete sign-in?")
                print("  Try running `axiv login` again.")
                return False

    except Exception as e:
        print(f"✗ Login browser failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Load credentials (kept for legacy / graph command use)
# ---------------------------------------------------------------------------

def load_credentials(secret_file: Optional[Path] = None) -> Tuple[Optional[str], Optional[str]]:
    """Load email and password from environment variables or SECRET.md."""
    import os, stat as _stat

    email    = os.getenv("ALPHAXIV_EMAIL")
    password = os.getenv("ALPHAXIV_PASSWORD")
    if email and password:
        return email, password

    if secret_file is None:
        secret_file = Path.cwd() / "SECRET.md"
    if not secret_file.exists():
        return None, None

    try:
        file_stat = os.stat(secret_file)
        if file_stat.st_mode & (_stat.S_IRWXG | _stat.S_IRWXO):
            print(f"⚠ {secret_file} has insecure permissions — run: chmod 600 {secret_file}")
            return None, None
    except OSError as e:
        print(f"⚠ Could not stat {secret_file}: {e}")
        return None, None

    for line in secret_file.read_text().split("\n"):
        if line.startswith("email:"):
            email = line.split(":", 1)[1].strip()
        elif line.startswith("passwd:") or line.startswith("password:"):
            password = line.split(":", 1)[1].strip()

    return email, password


# ---------------------------------------------------------------------------
# Overview generation (called by `axiv research link`)
# ---------------------------------------------------------------------------

def ensure_overview_generated(
    paper_id: str,
    version_id: str,
    client,
    secret_file: Optional[Path] = None,   # kept for API compat, no longer used
    headless: bool = True,
) -> bool:
    """
    Navigate to the paper's overview page with the saved session and click
    the Generate button.  Polls the API until the overview is ready.

    The saved session must already be valid — run `axiv login` first if not.
    """
    if not PLAYWRIGHT_AVAILABLE:
        print("    Playwright not installed — run: pip install playwright && playwright install chromium")
        return False

    # Quick session check
    if not is_session_valid():
        print("    ⚠ No valid alphaxiv session found.")
        print("    Run `axiv login` once to save your session, then retry.")
        return False

    print(f"    Requesting overview for {paper_id}…")
    try:
        with sync_playwright() as pw:
            ctx = _launch_context(pw, headless=headless)
            page = ctx.new_page()

            page.goto(
                f"{ALPHAXIV_WEB_URL}/overview/{paper_id}",
                wait_until="networkidle",
                timeout=30000,
            )
            page.wait_for_timeout(3000)

            # Click whichever generate/request button is present
            clicked = False
            for label in ("Generate", "generate", "Create overview", "Request"):
                try:
                    btn = page.locator(f'button:has-text("{label}")').first
                    if btn.is_visible(timeout=2000):
                        print(f"    Clicking '{label}'…")
                        btn.click()
                        page.wait_for_timeout(2000)
                        clicked = True
                        break
                except Exception:
                    pass

            if not clicked:
                logger.debug(f"No generate button found for {paper_id} — may already be queued")

            ctx.close()

        # Poll the API for up to 120 s
        print("    Polling for overview (up to 120 s)…")
        for _ in range(120):
            time.sleep(1)
            try:
                ov = client.get_overview(version_id)
                if ov and ov.get("overview"):
                    print("    ✓ Overview ready.")
                    return True
            except Exception:
                pass

        print("    ⚠ Timeout — overview may still be generating in the background.")
        return False

    except Exception as e:
        print(f"    ✗ Overview generation failed: {e}")
        return False


def is_playwright_available() -> bool:
    return PLAYWRIGHT_AVAILABLE
