#!/usr/bin/env python3
"""Overview generation using Playwright automation."""

import logging
import time
from pathlib import Path
from typing import Optional, Tuple

from config import ALPHAXIV_WEB_URL, BROWSER_PROFILE

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def load_credentials(secret_file: Optional[Path] = None) -> Tuple[Optional[str], Optional[str]]:
    """Load email and password from SECRET.md or environment."""
    import os
    import stat
    
    # Try environment variables first
    email = os.getenv("ALPHAXIV_EMAIL")
    password = os.getenv("ALPHAXIV_PASSWORD")
    
    if email and password:
        return email, password
    
    # Try SECRET.md file
    if secret_file is None:
        secret_file = Path.cwd() / "SECRET.md"
    
    if not secret_file.exists():
        return None, None
    
    # Security: Validate file permissions
    try:
        file_stat = os.stat(secret_file)
        # Check if file is readable by group or others (world)
        if file_stat.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            print(f"⚠ WARNING: {secret_file} has insecure permissions!")
            print(f"   Credentials file should be readable only by owner.")
            print(f"   Fix with: chmod 600 {secret_file}")
            print(f"   Refusing to load credentials from world/group-readable file.")
            return None, None
    except OSError as e:
        print(f"⚠ WARNING: Could not check permissions for {secret_file}: {e}")
        return None, None
    
    content = secret_file.read_text()
    for line in content.split('\n'):
        if line.startswith('email:'):
            email = line.split(':', 1)[1].strip()
        elif line.startswith('passwd:') or line.startswith('password:'):
            password = line.split(':', 1)[1].strip()
    
    return email, password


def check_login(page: 'Page') -> bool:
    """Check if user is logged in to alphaXiv."""
    try:
        page.goto(f"{ALPHAXIV_WEB_URL}/", wait_until="load", timeout=15000)
        page.wait_for_timeout(2000)
        signin_link = page.locator("a[href='/signin']").first
        return not signin_link.is_visible()
    except Exception as e:
        logger.warning(f"Login check failed: {e}")
        return False


def login_to_alphaxiv(page: 'Page', email: str, password: str) -> bool:
    """Login to alphaXiv using Google OAuth."""
    try:
        print("    Logging in to alphaXiv...")
        page.goto(f"{ALPHAXIV_WEB_URL}/signin", wait_until="load", timeout=30000)
        page.wait_for_timeout(3000)
        
        # Click Google login
        print("    Clicking Google login button...")
        page.locator('button:has-text("Continue with Google")').first.click(timeout=10000)
        page.wait_for_timeout(5000)
        
        # Enter email
        print("    Entering email...")
        email_input = page.locator('input[type="email"]').first
        email_input.wait_for(state="visible", timeout=15000)
        email_input.fill(email)
        page.keyboard.press("Enter")
        page.wait_for_timeout(5000)
        
        # Enter password
        print("    Entering password...")
        password_input = page.locator('input[type="password"]').first
        password_input.wait_for(state="visible", timeout=15000)
        password_input.fill(password)
        page.keyboard.press("Enter")
        page.wait_for_timeout(8000)
        
        # Handle confirmation if needed
        try:
            confirm_btn = page.locator("button:has-text('Confirm')").first
            if confirm_btn.is_visible(timeout=3000):
                print("    Clicking confirm...")
                confirm_btn.click()
        except Exception as e:
            logger.debug(f"No confirm button (expected): {e}")
        
        # Wait for redirect to alphaXiv
        print("    Waiting for redirect...")
        for i in range(30):
            time.sleep(1)
            if "alphaxiv.org" in page.url and "/signin" not in page.url:
                print("    ✓ Login successful!")
                return True
        
        print("    ⚠ Login timeout - may need manual intervention")
        return False
    except Exception as e:
        print(f"    ✗ Login failed: {e}")
        return False


def ensure_overview_generated(paper_id: str, version_id: str, client, secret_file: Optional[Path] = None, headless: bool = True) -> bool:
    """
    Ensure overview exists for a paper, generate if needed.
    
    Args:
        paper_id: arXiv ID (e.g., "2407.10654")
        version_id: alphaXiv version ID
        client: AlphaXivClient instance
        secret_file: Path to SECRET.md with credentials
        headless: Run browser in headless mode
    
    Returns:
        True if overview exists or was successfully generated
    """
    if not PLAYWRIGHT_AVAILABLE:
        print("    ⚠ Playwright not installed. Cannot generate overview.")
        print("    Install with: pip install playwright && playwright install chromium")
        return False
    
    # Check if overview already exists
    try:
        overview = client.get_overview(version_id)
        if overview and overview.get('overview'):
            return True
    except Exception as e:
        logger.debug(f"Could not fetch overview for {version_id}, will attempt generation: {e}")
    
    # Need to generate - load credentials
    email, password = load_credentials(secret_file)
    if not email or not password:
        print("    ⚠ No credentials found. Cannot generate overview.")
        print("    Set ALPHAXIV_EMAIL and ALPHAXIV_PASSWORD env vars, or create SECRET.md:")
        print("    email: your.email@gmail.com")
        print("    password: your_password")
        return False
    
    print(f"    🤖 Generating overview for {paper_id}...")
    
    context = None
    try:
        with sync_playwright() as playwright:
            import os
            import stat
            
            BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
            
            try:
                profile_stat = os.stat(BROWSER_PROFILE)
                if profile_stat.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
                    print(f"    ⚠ WARNING: Browser profile {BROWSER_PROFILE} has insecure permissions!")
                    print(f"    Fix with: chmod 700 {BROWSER_PROFILE}")
            except OSError:
                pass
            
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_PROFILE),
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
            )
            
            page = context.new_page()
            
            if not check_login(page):
                if not login_to_alphaxiv(page, email, password):
                    return False
            
            page.goto(f"{ALPHAXIV_WEB_URL}/overview/{paper_id}", wait_until="load")
            time.sleep(5)
            
            for pattern in ["Generate", "generate", "Create", "Request"]:
                try:
                    btn = page.locator(f'button:has-text("{pattern}")').first
                    if btn.is_visible(timeout=2000):
                        print(f"    Clicking: {pattern}")
                        btn.click()
                        time.sleep(2)
                        break
                except Exception as e:
                    logger.debug(f"Button '{pattern}' not found: {e}")
                    continue
            
            print("    ⏳ Waiting for overview generation (up to 90s)...")
            for i in range(90):
                time.sleep(1)
                
                try:
                    overview = client.get_overview(version_id)
                    if overview and overview.get('overview'):
                        print("    ✓ Overview generated successfully!")
                        return True
                except Exception as e:
                    logger.debug(f"Polling overview for {version_id}: {e}")
            
            print("    ⚠ Overview generation timeout. It may still be processing.")
            return False
            
    except Exception as e:
        print(f"    ✗ Overview generation failed: {e}")
        return False
    finally:
        if context:
            context.close()


def is_playwright_available() -> bool:
    """Check if Playwright is available."""
    return PLAYWRIGHT_AVAILABLE
