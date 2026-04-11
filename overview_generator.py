#!/usr/bin/env python3
"""
Overview generation using Playwright browser automation.

Login strategy
--------------
Three methods are tried in order:

  1. **Saved browser session** -- `axiv login` opens a VISIBLE browser,
     lets the user log in manually (Google OAuth, 2FA, whatever), then
     saves the session to disk.  Only needs to run once per machine /
     workspace.

  2. **Credential login** -- if no saved session exists, the module can
     log in programmatically using email/password from:
       - ALPHAXIV_EMAIL / ALPHAXIV_PASSWORD environment variables
       - A SECRET.md file (email: / password: lines)

  3. **No login** -- if neither method works, overview generation is
     skipped and the caller is told to run `axiv login`.
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
# Credential-based login (Clerk email/password form + Google OAuth)
# ---------------------------------------------------------------------------

def _credential_login(
    secret_file: Optional[Path] = None,
    headless: bool = True,
) -> bool:
    """
    Log in to alphaxiv.org using email/password credentials.

    Supports two login flows:
      1. **Clerk email/password** -- for accounts with password authentication.
         Fills both email and password in the Clerk form, then clicks Continue.
      2. **Google OAuth** -- for Google-linked accounts. After the Clerk form
         redirects to accounts.google.com, fills in email and password on
         Google's login page.

    Note: Google blocks automated logins from headless browsers.
    If the account only supports Google OAuth and headless=True, this will
    fail.  Use `axiv login` for interactive Google OAuth instead.

    Returns True if login succeeded.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return False

    email, password = load_credentials(
        Path(secret_file) if secret_file else None,
    )
    if not email or not password:
        logger.debug("_credential_login: no credentials available")
        return False

    logger.debug(f"_credential_login: attempting login as {email}")

    try:
        with sync_playwright() as pw:
            ctx = _launch_context(pw, headless=headless)
            page = ctx.new_page()

            # Navigate to sign-in page
            page.goto(
                f"{ALPHAXIV_WEB_URL}/signin",
                wait_until="load",
                timeout=30000,
            )
            page.wait_for_timeout(3000)

            # Fill both email and password before clicking Continue
            email_field = page.locator("#identifier-field")
            email_field.wait_for(state="visible", timeout=10000)
            email_field.fill(email)
            page.wait_for_timeout(300)

            password_field = page.locator("#password-field")
            if password_field.is_visible():
                password_field.fill(password)
                page.wait_for_timeout(300)

            # Click Continue
            continue_btn = page.locator('button:has-text("Continue")').first
            continue_btn.click()
            page.wait_for_timeout(5000)

            # Check if we were redirected to Google OAuth
            if "accounts.google.com" in page.url:
                logger.debug("Redirected to Google OAuth -- attempting Google login")
                ok = _google_oauth_login(page, email, password)
                if not ok:
                    ctx.close()
                    return False
            else:
                # On Clerk -- password might need a second step
                pw2 = page.locator("#password-field")
                if pw2.is_visible():
                    pw2.fill(password)
                    page.wait_for_timeout(300)
                    page.locator('button:has-text("Continue")').first.click()
                    page.wait_for_timeout(5000)

            # Navigate to alphaxiv home and verify login
            signed_in = check_login(page)
            ctx.close()

            if signed_in:
                logger.info("Credential login successful -- session saved.")
                return True
            else:
                logger.warning("Credential login: form submitted but session not verified.")
                return False

    except Exception as e:
        logger.debug(f"_credential_login failed: {e}")
        return False


def _google_oauth_login(page: "Page", email: str, password: str) -> bool:
    """
    Complete the Google OAuth flow on accounts.google.com.

    Google actively blocks automated/headless logins. This function
    will attempt the flow but may fail with "This browser or app may
    not be secure" for headless browsers.

    Returns True if the login form was submitted (redirect back to
    alphaxiv is pending).
    """
    try:
        # Fill Google email
        email_input = page.locator("#identifierId")
        if email_input.is_visible(timeout=5000):
            email_input.fill(email)
            page.wait_for_timeout(500)
            page.locator("#identifierNext button").click()
            page.wait_for_timeout(5000)
        else:
            logger.debug("Google email field not found")
            return False

        # Check if Google rejected the login
        if "/signin/rejected" in page.url:
            logger.warning(
                "Google blocked automated login. "
                "Run `axiv login` to sign in interactively."
            )
            return False

        # Fill Google password
        pw_input = page.locator('input[name="Passwd"]')
        if pw_input.is_visible(timeout=5000):
            pw_input.fill(password)
            page.wait_for_timeout(500)
            page.locator("#passwordNext button").click()
            page.wait_for_timeout(8000)

            # Check for redirect back to alphaxiv
            if "alphaxiv" in page.url:
                return True
            elif "challenge" in page.url or "rejected" in page.url:
                logger.warning("Google requires additional verification (2FA/challenge).")
                return False
            return True
        else:
            logger.debug("Google password field not visible")
            return False

    except Exception as e:
        logger.debug(f"_google_oauth_login failed: {e}")
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

    print("Opening browser -- log in to alphaxiv.org in the window that appears.")
    print("Come back here and press Enter once you are logged in.\n")

    try:
        with sync_playwright() as pw:
            ctx = _launch_context(pw, headless=False)
            page = ctx.new_page()
            page.goto(f"{ALPHAXIV_WEB_URL}/signin", wait_until="load", timeout=30000)

            # Hand control to the user
            input("Press Enter after you have finished logging in... ")

            # Verify: navigate to home and check we're logged in
            try:
                page.goto(f"{ALPHAXIV_WEB_URL}/", wait_until="load", timeout=15000)
                page.wait_for_timeout(1500)
                signed_in = not page.locator("a[href='/signin']").first.is_visible()
            except Exception:
                signed_in = False

            ctx.close()

            if signed_in:
                print("Login verified -- session saved to browser profile.")
                return True
            else:
                print("Could not verify login. Did you complete sign-in?")
                print("  Try running `axiv login` again.")
                return False

    except Exception as e:
        print(f"Login browser failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Load credentials (from env vars or SECRET.md)
# ---------------------------------------------------------------------------

def load_credentials(secret_file: Optional[Path] = None) -> Tuple[Optional[str], Optional[str]]:
    """Load email and password from environment variables or SECRET.md."""
    import os, stat as _stat

    email    = os.getenv("ALPHAXIV_EMAIL")
    password = os.getenv("ALPHAXIV_PASSWORD")
    if email and password:
        return email, password

    if secret_file is None:
        # Use the resolved workspace root, not cwd(), to avoid reading a
        # malicious SECRET.md from an arbitrary working directory.
        from alphaxiv_cli.context import get_context
        secret_file = Path(get_context().root) / "SECRET.md"
    if not secret_file.exists():
        return None, None

    try:
        file_stat = os.stat(secret_file)
        if file_stat.st_mode & (_stat.S_IRWXG | _stat.S_IRWXO):
            print(f"Warning: {secret_file} has insecure permissions -- run: chmod 600 {secret_file}")
            return None, None
    except OSError as e:
        print(f"Warning: Could not stat {secret_file}: {e}")
        return None, None

    for line in secret_file.read_text().split("\n"):
        if line.startswith("email:"):
            email = line.split(":", 1)[1].strip()
        elif line.startswith("passwd:") or line.startswith("password:"):
            password = line.split(":", 1)[1].strip()

    return email, password


# ---------------------------------------------------------------------------
# Overview generation (called by `axiv research link` / `start -g`)
# ---------------------------------------------------------------------------

def _trigger_one_paper(page: "Page", paper_id: str, client, version_id: str) -> str:
    """Navigate to a paper's overview page, click Generate, and verify.

    Uses an already-open *page* (shared browser context).  After clicking
    the button, polls the API for up to 15 seconds to confirm the backend
    acknowledged the request (status changes from None to something).

    Returns
    -------
    str
        ``"ok"`` if triggered/already exists, ``"rate_limited"`` if the site
        showed a rate-limit message, or ``"failed"`` otherwise.
    """
    from alphaxiv_cli.client import has_overview_content

    # Already has content? Skip.
    try:
        ov = client.get_overview(version_id, use_cache=False)
        if has_overview_content(ov):
            logger.debug(f"{paper_id}: overview already exists, skipping")
            return "ok"
    except Exception:
        pass

    try:
        page.goto(
            f"{ALPHAXIV_WEB_URL}/overview/{paper_id}",
            wait_until="load",
            timeout=30_000,
        )
        page.wait_for_timeout(3_000)
    except Exception as e:
        logger.debug(f"{paper_id}: page load failed: {e}")
        return "failed"

    # Try to click a generate button
    clicked = False
    for label in ("Generate", "generate", "Create overview", "Request"):
        try:
            btn = page.locator(f'button:has-text("{label}")').first
            if btn.is_visible(timeout=3_000):
                btn.click()
                page.wait_for_timeout(2_000)
                clicked = True
                break
        except Exception:
            pass

    if not clicked:
        logger.debug(f"{paper_id}: no generate button found (may already be queued)")
        # Still check API -- generation might already be in progress
        try:
            status = client.get_overview_status(version_id)
            if status and status.get("state"):
                return "ok"
        except Exception:
            pass
        return "failed"

    # Check for rate-limit toast/notification in the page after clicking.
    # AlphaXiv shows messages like "generating blogs too quickly" as toasts.
    _rate_limit_detected = False
    try:
        body_text = page.inner_text("body", timeout=2_000).lower()
        _rate_phrases = ["too quickly", "rate limit", "try again", "wait a moment", "please wait"]
        for phrase in _rate_phrases:
            if phrase in body_text:
                _rate_limit_detected = True
                logger.warning(
                    f"{paper_id}: rate-limit detected ('{phrase}' found in page)"
                )
                break
    except Exception:
        pass

    if _rate_limit_detected:
        return "rate_limited"

    # Verify: poll API briefly to confirm generation was accepted
    for _ in range(5):
        time.sleep(3)
        try:
            status = client.get_overview_status(version_id)
            if status and status.get("state"):
                logger.debug(f"{paper_id}: generation confirmed (state={status['state']})")
                return "ok"
        except Exception:
            pass

    # Button was clicked but API didn't confirm -- still treat as triggered
    logger.debug(f"{paper_id}: clicked but API status not confirmed")
    return "ok"


def trigger_overviews_batch(
    papers: dict,          # {paper_id: version_id}
    client,
    secret_file: Optional[Path] = None,
    headless: bool = True,
    delay: float = 120.0,
    on_progress=None,      # callback(paper_id, status: str)
) -> dict:
    """Trigger overview generation for multiple papers using a single browser.

    Opens one Playwright persistent context, ensures login, then visits
    each paper's overview page in sequence.  After clicking Generate,
    verifies the trigger via the API before moving on.

    Parameters
    ----------
    papers : dict
        ``{paper_id: version_id}`` of papers to trigger.
    client : AlphaXivClient
        API client for verification polling.
    secret_file : Path, optional
        Path to SECRET.md for credential login fallback.
    headless : bool
        Run browser headless (default True).
    delay : float
        Seconds to wait between papers to avoid rate limits (default 60).
    on_progress : callable, optional
        Called as ``on_progress(paper_id, status)`` after each attempt.
        *status* is ``"ok"``, ``"rate_limited"``, or ``"failed"``.

    Returns
    -------
    dict
        ``{paper_id: True/False}`` indicating which were triggered.
    """
    if not PLAYWRIGHT_AVAILABLE or not papers:
        return {}

    results = {}
    rate_limit_backoff = 120  # extra seconds to wait on rate-limit

    try:
        with sync_playwright() as pw:
            ctx = _launch_context(pw, headless=headless)
            page = ctx.new_page()

            # Verify login once
            if not check_login(page):
                logger.debug("Session invalid -- attempting credential login")
                ctx.close()
                if not _credential_login(secret_file=secret_file, headless=headless):
                    logger.warning("Cannot log in -- aborting batch trigger")
                    return {}
                # Re-open context after credential login saved the session
                ctx = _launch_context(pw, headless=headless)
                page = ctx.new_page()

            for i, (pid, vid) in enumerate(papers.items()):
                if i > 0:
                    time.sleep(delay)

                status = _trigger_one_paper(page, pid, client, vid)

                # On rate-limit: notify, back off, then retry once
                if status == "rate_limited":
                    if on_progress:
                        on_progress(pid, "rate_limited")
                    logger.info(
                        f"{pid}: rate-limited, waiting {rate_limit_backoff}s before retry"
                    )
                    time.sleep(rate_limit_backoff)
                    status = _trigger_one_paper(page, pid, client, vid)

                results[pid] = (status == "ok")
                if on_progress:
                    on_progress(pid, status)

            ctx.close()

    except Exception as e:
        logger.warning(f"trigger_overviews_batch failed: {e}")

    return results


def ensure_overview_generated(
    paper_id: str,
    version_id: str,
    client,
    secret_file: Optional[Path] = None,
    headless: bool = True,
) -> bool:
    """Trigger overview generation for a single paper.

    Convenience wrapper around ``trigger_overviews_batch`` for callers
    that only need to trigger one paper.  For multiple papers, prefer
    ``trigger_overviews_batch`` directly to reuse the browser context.
    """
    results = trigger_overviews_batch(
        {paper_id: version_id},
        client,
        secret_file=secret_file,
        headless=headless,
        delay=0,
    )
    return results.get(paper_id, False)


def is_playwright_available() -> bool:
    return PLAYWRIGHT_AVAILABLE
