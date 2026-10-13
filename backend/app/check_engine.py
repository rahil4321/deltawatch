from __future__ import annotations

import hashlib
import os
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image, ImageChops, ImageEnhance, ImageOps
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .config import ARTIFACTS_DIR, CHECK_TIMEOUT_SECONDS, MAX_CAPTURE_TEXT_CHARS, USER_AGENT
from .security import UnsafeTargetError, validate_public_url


class PageCaptureError(RuntimeError):
    pass


class PageBlockedError(PageCaptureError):
    pass


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_text(text: str, ignored_phrases: list[str] | None = None) -> str:
    """Normalize rendered text and apply exact, user-configured noise exclusions."""
    text = (text or "").replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    cleaned: list[str] = []
    for line in text.split("\n"):
        line = re.sub(r"[\t\f\v ]+", " ", line).strip()
        if line:
            cleaned.append(line)
    result = "\n".join(cleaned)
    for phrase in ignored_phrases or []:
        phrase = str(phrase).strip()
        if phrase:
            result = result.replace(phrase, "")
    # Keep paragraph structure stable when an ignored phrase leaves empty lines.
    return "\n".join(line.strip() for line in result.splitlines() if line.strip())


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _browser_route_is_allowed(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    try:
        validate_public_url(url, resolve_dns=True)
        return True
    except (UnsafeTargetError, ValueError, OSError, socket.error):
        return False


def classify_http_status(status: int | None) -> None:
    """Fail closed for access challenges, missing pages and server outages."""
    if status is None:
        return
    if status in {401, 403, 407, 408, 418, 429, 451}:
        raise PageBlockedError(f"The website returned HTTP {status}; it may be protected, challenged or rate-limited. No content-change alert was sent.")
    if status in {404, 410}:
        raise PageBlockedError(f"The monitored URL returned HTTP {status}; the page may have moved or been removed. Review the URL instead of treating this as a content change.")
    if status >= 500:
        raise PageCaptureError(f"The monitored website returned HTTP {status} (server error). This was recorded as a check failure, not a content change.")


def is_access_challenge(final_url: str, title: str, visible_text: str) -> bool:
    """Detect common CAPTCHA/bot-gate screens without confusing them with page changes."""
    challenge_text = f"{title} {visible_text[:10000]}".lower()
    challenge_patterns = (
        r"\bverify you are human\b", r"\bi am not a robot\b",
        r"\bcomplete the captcha\b", r"\bchecking your browser\b",
        r"\bjust a moment\.\.\.", r"\brobot check\b",
        r"\baccess denied\b", r"\bsecurity challenge\b",
    )
    final_path = urlparse(final_url).path.lower()
    return any(re.search(pattern, challenge_text) for pattern in challenge_patterns) or any(
        token in final_path for token in ("/captcha", "/challenge-platform", "/cdn-cgi/challenge")
    )


def capture_page(monitor: dict[str, Any]) -> dict[str, Any]:
    """Render a public page with Playwright and persist a viewport screenshot."""
    url = validate_public_url(monitor["url"])
    monitor_id = int(monitor["id"])
    selectors = monitor.get("ignore_selectors") or []
    ignored_text = monitor.get("ignore_text") or []
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    screenshot_dir = ARTIFACTS_DIR / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_file = screenshot_dir / f"monitor-{monitor_id}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.png"

    executable = os.getenv("DELTAWATCH_CHROMIUM_EXECUTABLE")
    try:
        with sync_playwright() as playwright:
            browser_args = ["--disable-dev-shm-usage"]
            # Chromium refuses to run as root without disabling its sandbox. Normal local
            # laptop runs keep the sandbox on; production workers should run as non-root.
            if (hasattr(os, "geteuid") and os.geteuid() == 0) or os.getenv("DELTAWATCH_CHROMIUM_NO_SANDBOX", "false").lower() in {"1", "true", "yes"}:
                browser_args.append("--no-sandbox")
            launch_options: dict[str, Any] = {"headless": True, "args": browser_args}
            if executable:
                launch_options["executable_path"] = executable
            browser = playwright.chromium.launch(**launch_options)
            try:
                context = browser.new_context(
                    viewport={"width": 1365, "height": 820},
                    device_scale_factor=1,
                    user_agent=USER_AGENT,
                    locale="en-US",
                    color_scheme="light",
                    java_script_enabled=True,
                    accept_downloads=False,
                    service_workers="block",
                )

                checked_hosts: set[str] = set()

                def guard_route(route: Any) -> None:
                    request_url = route.request.url
                    parsed_request = urlparse(request_url)
                    host = (parsed_request.hostname or "").lower().rstrip(".")
                    try:
                        if host and host in checked_hosts:
                            # Keep checking scheme, credentials, localhost suffixes and literal IPs;
                            # DNS was resolved and checked the first time this hostname appeared.
                            validate_public_url(request_url, resolve_dns=False)
                            allowed = parsed_request.scheme in {"http", "https"}
                        else:
                            allowed = _browser_route_is_allowed(request_url)
                            if allowed:
                                checked_hosts.add(host)
                    except Exception:
                        allowed = False
                    try:
                        if allowed:
                            route.continue_()
                        else:
                            route.abort("blockedbyclient")
                    except Exception:
                        # A request may be cancelled by the page before the route callback runs.
                        pass

                context.route("**/*", guard_route)

                def block_websocket(websocket_route: Any) -> None:
                    # WebSocket requests bypass ordinary HTTP routes in Chromium; close them
                    # explicitly so a page cannot use ws:// to probe local/private services.
                    try:
                        websocket_route.close(code=1008, reason="WebSocket connections are disabled during monitored capture.")
                    except Exception:
                        pass

                context.route_web_socket("**/*", block_websocket)
                page = context.new_page()
                page.set_default_navigation_timeout(CHECK_TIMEOUT_SECONDS * 1000)
                page.set_default_timeout(7000)
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=CHECK_TIMEOUT_SECONDS * 1000)
                except PlaywrightTimeoutError as exc:
                    raise PageCaptureError(f"Page load timed out after {CHECK_TIMEOUT_SECONDS} seconds.") from exc
                classify_http_status(response.status if response is not None else None)
                try:
                    page.wait_for_timeout(350)
                    title = page.title()[:300]
                    capture_script = """({selector, ignoredSelectors, maxChars}) => {
                      let root;
                      try { root = selector ? document.querySelector(selector) : document.body; }
                      catch (error) { return {error: 'INVALID_SELECTOR'}; }
                      if (!root) return {error: 'SELECTOR_NOT_FOUND'};
                      const excluded = new Set();
                      try {
                        for (const sel of ignoredSelectors) root.querySelectorAll(sel).forEach(node => excluded.add(node));
                      } catch (error) { return {error: 'INVALID_IGNORE_SELECTOR'}; }
                      const removals = [];
                      for (const node of excluded) {
                        removals.push({node, parent: node.parentNode, next: node.nextSibling});
                        node.remove();
                      }
                      let text = '';
                      try { text = root.innerText || root.textContent || ''; }
                      finally {
                        for (let i = removals.length - 1; i >= 0; i--) {
                          const item = removals[i];
                          if (item.parent) item.parent.insertBefore(item.node, item.next && item.next.parentNode === item.parent ? item.next : null);
                        }
                      }
                      return {text: text.slice(0, maxChars)};
                    }"""
                    extracted = page.evaluate(capture_script, {"selector": monitor.get("selector") or None, "ignoredSelectors": selectors, "maxChars": MAX_CAPTURE_TEXT_CHARS})
                    if extracted.get("error") == "INVALID_SELECTOR":
                        raise PageCaptureError("The CSS selector is invalid. Please correct it in monitor settings.")
                    if extracted.get("error") == "SELECTOR_NOT_FOUND":
                        raise PageCaptureError("The configured CSS selector was not found on this page.")
                    if extracted.get("error") == "INVALID_IGNORE_SELECTOR":
                        raise PageCaptureError("An ignore CSS selector is invalid. Please correct it in monitor settings.")
                    raw_text = str(extracted.get("text", ""))[:MAX_CAPTURE_TEXT_CHARS]
                    visible_text = normalize_text(raw_text, ignored_text)
                    if not visible_text:
                        raise PageCaptureError("No visible text was captured. Check the URL or CSS selector.")
                    final_url = page.url
                    if is_access_challenge(final_url, title, visible_text):
                        raise PageBlockedError("The page appears to show a CAPTCHA, bot challenge or access-denied screen. It was not recorded as a content change.")
                    page.screenshot(path=str(screenshot_file), type="png", animations="disabled", caret="hide")
                    if not _browser_route_is_allowed(final_url):
                        raise PageBlockedError("The page redirected to a private or restricted destination; navigation was stopped.")
                finally:
                    context.close()
            finally:
                browser.close()
    except UnsafeTargetError:
        raise
    except (PageCaptureError, PageBlockedError):
        raise
    except Exception as exc:
        message = str(exc)
        if "ERR_BLOCKED_BY_CLIENT" in message or "blockedbyclient" in message.lower():
            raise PageBlockedError("The page attempted to load a blocked or restricted resource.") from exc
        raise PageCaptureError(f"Browser capture failed: {message[:240]}") from exc

    relative = screenshot_file.relative_to(ARTIFACTS_DIR).as_posix()
    return {
        "created_at": timestamp(),
        "title": title or urlparse(final_url).hostname or "Untitled page",
        "final_url": final_url,
        "text_content": visible_text,
        "content_hash": content_hash(visible_text),
        "screenshot_path": relative,
    }


def build_text_diff(previous: str, current: str, *, max_chars: int = 6000) -> dict[str, Any]:
    """Return readable line additions/removals and a fine-grained character change ratio."""
    import difflib

    char_matcher = difflib.SequenceMatcher(a=previous, b=current, autojunk=True)
    changed_chars = sum(
        (i2 - i1) + (j2 - j1)
        for tag, i1, i2, j1, j2 in char_matcher.get_opcodes()
        if tag != "equal"
    )
    # Line-level evidence keeps a changed price/deadline legible instead of showing
    # arbitrary character fragments such as "12" and "5" from a digit replacement.
    line_matcher = difflib.SequenceMatcher(a=previous.splitlines(), b=current.splitlines(), autojunk=True)
    added: list[str] = []
    removed: list[str] = []
    for tag, i1, i2, j1, j2 in line_matcher.get_opcodes():
        if tag in {"delete", "replace"}:
            removed.extend(line.strip() for line in previous.splitlines()[i1:i2] if line.strip())
        if tag in {"insert", "replace"}:
            added.extend(line.strip() for line in current.splitlines()[j1:j2] if line.strip())
    denominator = max(len(previous) + len(current), 1)
    change_percent = min(100.0, changed_chars / denominator * 100.0)
    added_text = "\n".join(added)[:max_chars]
    removed_text = "\n".join(removed)[:max_chars]
    summary = f"{len(added_text)} characters of additions and {len(removed_text)} characters of removals" if (added_text or removed_text) else "Rendered content changed"
    return {
        "added_text": added_text,
        "removed_text": removed_text,
        "changed_chars": changed_chars,
        "change_percent": round(change_percent, 4),
        "summary": summary,
    }


def create_visual_diff(previous_path: str | None, current_path: str | None, monitor_id: int, event_id_hint: str) -> str | None:
    """Save an amplified screenshot difference; returns an artifacts-relative path."""
    if not previous_path or not current_path:
        return None
    previous_file = ARTIFACTS_DIR / previous_path
    current_file = ARTIFACTS_DIR / current_path
    if not previous_file.is_file() or not current_file.is_file():
        return None
    output_dir = ARTIFACTS_DIR / "diffs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"monitor-{monitor_id}-diff-{event_id_hint}.png"
    try:
        with Image.open(previous_file) as old_img, Image.open(current_file) as new_img:
            old_img = old_img.convert("RGB")
            new_img = new_img.convert("RGB")
            if old_img.size != new_img.size:
                new_img = new_img.resize(old_img.size)
            difference = ImageChops.difference(old_img, new_img)
            difference = ImageEnhance.Contrast(difference).enhance(3.0)
            difference = ImageOps.autocontrast(difference)
            # Make changed regions legible against a neutral canvas while preserving geometry.
            difference.save(output_file, format="PNG", optimize=True)
        return output_file.relative_to(ARTIFACTS_DIR).as_posix()
    except (OSError, ValueError):
        return None
