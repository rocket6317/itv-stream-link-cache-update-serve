#!/usr/bin/env python3
"""
ITVX Password Login using Chrome Automation
- Starts at homepage like a real user
- Uses random delays to mimic human behavior
- Logs structured events to event_tracker for pattern analysis
"""

import subprocess
import time
import requests
import json
import os
import sys
import tempfile
import shutil
import random
import xml.etree.ElementTree as ET
import re
from datetime import datetime, timezone

# Global to track temp profile for cleanup
temp_profile = None
message_id = 100  # Start from 100 to avoid conflicts


def get_app_dir():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(script_dir)


def get_stack_env_path():
    return os.environ.get("ITV_STACK_ENV", os.path.join(get_app_dir(), "stack.env"))


def get_logs_dir():
    return os.environ.get("ITV_LOG_DIR", os.path.join(get_app_dir(), "logs"))


# Event tracking integration
EVENT_TRACKER_AVAILABLE = False
try:
    # Add parent directory to path to import event_tracker
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    from event_tracker import log_event
    EVENT_TRACKER_AVAILABLE = True
except ImportError:
    # Stub implementation if event_tracker is not available
    def log_event(event_type, details=None, severity='info'):
        pass


def log_automation_event(event_type, details=None, severity='info'):
    """Log an automation event, falling back to print if event_tracker unavailable."""
    if EVENT_TRACKER_AVAILABLE:
        log_event(event_type, details, severity)
    else:
        # Fallback to print logging
        print(f"[{severity.upper()}] {event_type}: {details}")

def random_delay(min_sec, max_sec):
    """Human-like random delay"""
    delay = random.uniform(min_sec, max_sec)
    print(f"[{delay:.1f}s]", end="", flush=True)
    time.sleep(delay)
    print()

def exponential_backoff(attempt, base_delay=2, max_delay=60):
    """Calculate exponential backoff with jitter

    Args:
        attempt: Retry attempt number (0-indexed)
        base_delay: Base delay in seconds (default: 2)
        max_delay: Maximum delay in seconds (default: 60)

    Returns:
        Delay in seconds with jitter applied
    """
    delay = min(base_delay * (2 ** attempt), max_delay)
    # Add jitter (±25%)
    jitter = delay * 0.25 * (random.random() * 2 - 1)
    return max(1, delay + jitter)

def retry_with_backoff(func, max_attempts=3, operation_name="operation", *args, **kwargs):
    """Retry a function with exponential backoff

    Args:
        func: Function to retry
        max_attempts: Maximum number of attempts (default: 3)
        operation_name: Name of operation for logging (default: "operation")
        *args, **kwargs: Arguments to pass to func

    Returns:
        Function result or {'error': error_message} on failure
    """
    last_error = None

    for attempt in range(max_attempts):
        try:
            result = func(*args, **kwargs)
            if result and not result.get('error'):
                return result
            last_error = result.get('error', 'Unknown error')
        except Exception as e:
            last_error = str(e)

        if attempt < max_attempts - 1:
            delay = exponential_backoff(attempt)
            print(f"{operation_name} failed (attempt {attempt + 1}/{max_attempts}): {last_error}")
            print(f"Retrying in {delay:.1f}s...")
            time.sleep(delay)

    print(f"{operation_name} failed after {max_attempts} attempts")
    return {'error': last_error}

def log_page_state(ws, context=""):
    """Log current page state for debugging

    Args:
        ws: WebSocket connection to Chrome
        context: Context string for logging (e.g., "after email fill")

    Returns:
        Page state dict with url, title, buttons, inputs, headings
    """
    state_script = """
    (function() {
        // Get all visible buttons
        const visibleButtons = Array.from(document.querySelectorAll('button'))
            .filter(b => b.offsetParent !== null)
            .map(b => b.textContent.trim())
            .filter(t => t.length > 0);

        // Get all visible inputs
        const visibleInputs = Array.from(document.querySelectorAll('input'))
            .filter(i => i.offsetParent !== null)
            .map(i => ({
                type: i.type,
                name: i.name || '',
                id: i.id || '',
                placeholder: i.placeholder || '',
                value: i.value ? '*' : ''
            }));

        // Get headings
        const headings = Array.from(document.querySelectorAll('h1, h2, h3, h4'))
            .map(h => h.textContent.trim())
            .filter(t => t.length > 0);

        // Check for error states
        const pageText = document.body.textContent.toLowerCase();
        const errorIndicators = [
            'something went wrong',
            'error occurred',
            'page not found',
            'service unavailable'
        ];
        const hasError = errorIndicators.some(indicator => pageText.includes(indicator));

        // Check for modals
        const modals = document.querySelectorAll('[role="dialog"], .modal, .popup, [class*="cookie"], [id*="cookie"]');
        const visibleModals = Array.from(modals)
            .filter(m => m.offsetParent !== null)
            .map(m => m.textContent.trim().substring(0, 100));

        return {
            url: window.location.href,
            title: document.title,
            visibleButtons: visibleButtons.slice(0, 20),  // Limit output
            visibleInputs: visibleInputs.slice(0, 10),
            headings: headings.slice(0, 10),
            hasError: hasError,
            visibleModals: visibleModals.slice(0, 3)
        };
    })()
    """
    try:
        result = run_js(ws, state_script, timeout=10)
        if result and 'result' in result:
            inner_result = result.get('result', {})
            if isinstance(inner_result, dict) and 'value' in inner_result:
                state = inner_result.get('value', {})
            else:
                state = inner_result
        else:
            state = {}

        if context:
            print(f"Page state [{context}]:")
            for key, value in state.items():
                if key == 'url':
                    print(f"  {key}: {value}")
                elif isinstance(value, list) and value:
                    print(f"  {key}: {value[:5]}")  # Show first 5 items
        return state
    except Exception as e:
        print(f"Error logging page state: {e}")
        return {}

def dismiss_cookie_consent(ws):
    """Detect and dismiss cookie consent modal if present

    Args:
        ws: WebSocket connection to Chrome

    Returns:
        {'dismissed': bool, 'method': str} or {'error': str}
    """
    dismiss_script = """
    (function() {
        // Try multiple cookie consent selectors and methods
        const strategies = [];

        // Strategy 1: Common cookie consent button selectors
        const consentSelectors = [
            'button#onetrust-accept-btn-handler',
            'button[data-consent="accept"]',
            'button[aria-label*="Accept" i]',
            'button[aria-label*="accept" i]',
            '.accept-cookies',
            '#accept-cookies',
            'button:contains("Accept")',
            'button:contains("Accept All")',
            'button:contains("Accept all")',
            'button.cookie-accept',
            'button[data-cookie-accept]',
        ];

        for (const selector of consentSelectors) {
            try {
                const btn = document.querySelector(selector);
                if (btn && btn.offsetParent !== null) {
                    btn.click();
                    strategies.push({method: 'selector', value: selector, text: btn.textContent.trim()});
                }
            } catch (e) {}
        }

        // Strategy 2: Look for buttons with "Accept" text in visible modals
        const modals = document.querySelectorAll('[role="dialog"], .modal, .popup, [class*="cookie"], [id*="cookie"]');
        for (const modal of modals) {
            if (modal.offsetParent === null) continue;

            const buttons = modal.querySelectorAll('button');
            for (const btn of buttons) {
                const text = btn.textContent.trim().toLowerCase();
                if (text === 'accept' || text === 'accept all' || text === 'accept cookies') {
                    btn.click();
                    strategies.push({method: 'modal', text: btn.textContent.trim()});
                }
            }
        }

        // Strategy 3: Generic text search for Accept/Reject/Manage buttons
        const allButtons = Array.from(document.querySelectorAll('button'));
        for (const btn of allButtons) {
            if (btn.offsetParent === null) continue;

            const text = btn.textContent.trim().toLowerCase();
            // Skip if button is part of a form (likely not cookie consent)
            if (btn.closest('form')) continue;

            if (text === 'accept' || text === 'accept all' ||
                text.startsWith('accept ') ||
                (text.length < 30 && (text.includes('accept') || text.includes('agree')))) {
                // Check if there's a corresponding reject/manage button nearby (indicates cookie banner)
                const parent = btn.closest('[role="dialog"], .modal, .popup, div');
                if (parent) {
                    const siblings = parent.textContent.toLowerCase();
                    if (siblings.includes('reject') || siblings.includes('manage') || siblings.includes('cookie')) {
                        btn.click();
                        strategies.push({method: 'generic', text: btn.textContent.trim()});
                    }
                }
            }
        }

        return {
            dismissed: strategies.length > 0,
            strategies: strategies,
            modalCount: modals.length,
            totalButtons: allButtons.length
        };
    })()
    """

    result = run_js(ws, dismiss_script, timeout=15)

    if result and 'result' in result:
        inner_result = result.get('result', {})
        if isinstance(inner_result, dict) and 'value' in inner_result:
            value = inner_result.get('value', {})
            if isinstance(value, dict):
                if value.get('dismissed'):
                    print(f"Cookie consent dismissed using: {value.get('strategies', [])}")
                    return {'dismissed': True, 'strategies': value.get('strategies', [])}
                else:
                    print("No cookie consent modal found (or already dismissed)")
                    return {'dismissed': False}

    return {'dismissed': False}

def get_passcode_from_rss(feed_url, max_retries=2, max_age_minutes=5, initial_wait=20):
    """Retrieve passcode from kill-the-newsletter Atom/RSS feed with retries

    Uses HTTP conditional requests (ETag/Last-Modified) to check for updates
    without consuming rate limit quota. Only fetches full feed when changed.

    Args:
        max_retries: Number of retries (default: 2)
        max_age_minutes: Max age of email to accept (default: 5 minutes)
        initial_wait: Seconds to wait before first fetch (default: 20s)
    """
    # Define namespaces as constants (avoid f-string issues with {http://...})
    ATOM_NS = '{http://www.w3.org/2005/Atom}'
    RSS_CONTENT_NS = '{http://purl.org/rss/1.0/modules/content/}'

    # Track HTTP caching headers for conditional requests
    etag = None
    last_modified = None
    first_attempt = True

    print(f"Fetching passcode from feed (max age: {max_age_minutes} minutes)...")

    for attempt in range(1, max_retries + 1):
        try:
            # Wait longer on first attempt for email to arrive
            if first_attempt:
                print(f"Waiting {initial_wait}s for email to arrive...")
                time.sleep(initial_wait)
                first_attempt = False

            # Build conditional request headers to avoid consuming quota
            headers = {}
            if etag:
                headers['If-None-Match'] = etag
            if last_modified:
                headers['If-Modified-Since'] = last_modified

            response = requests.get(feed_url, headers=headers, timeout=30)

            # Check if feed hasn't changed (304 Not Modified)
            if response.status_code == 304:
                print(f"Attempt {attempt}/{max_retries}: Feed unchanged, waiting for new email...")
                if attempt < max_retries:
                    wait_time = 10  # Fixed 10s wait between checks
                    print(f"Waiting {wait_time}s before checking again...")
                    time.sleep(wait_time)
                continue

            # Check for rate limiting (kill-the-newsletter returns 403 with text "Rate limit")
            if response.status_code == 403 or response.status_code == 429:
                print(f"Attempt {attempt}/{max_retries}: Rate limited ({response.status_code})")
                print("kill-the-newsletter rate limit: 1 hour. Script cannot continue.")
                print("Wait 1 hour before running again, or run script less frequently.")
                return None  # Give up immediately - no point retrying within 1 hour

            response.raise_for_status()

            # Save caching headers for next request
            etag = response.headers.get('ETag')
            last_modified = response.headers.get('Last-Modified')

            root = ET.fromstring(response.content)

            # Detect format: Atom uses <entry>, RSS uses <item>
            atom_items = root.findall(f'.//{ATOM_NS}entry')
            rss_items = root.findall('.//item')

            if atom_items:
                items = atom_items
                format_type = 'Atom'
                date_tag = ATOM_NS + 'published'
                content_tag = ATOM_NS + 'content'
                summary_tag = ATOM_NS + 'summary'
                updated_tag = ATOM_NS + 'updated'
            elif rss_items:
                items = rss_items
                format_type = 'RSS'
                date_tag = 'pubDate'
                content_tag = 'description'
                summary_tag = None
                updated_tag = None
            else:
                print(f"Attempt {attempt}/{max_retries}: No items found in feed")
                if attempt < max_retries:
                    wait_time = 10
                    print(f"Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                continue

            print(f"Found {len(items)} emails in {format_type} feed")

            # Find the most recent item by date
            latest_item = None
            latest_date = None

            for item in items:
                date_elem = item.find(date_tag)
                if date_elem is None and format_type == 'Atom':
                    date_elem = item.find(updated_tag)  # Try <updated> as fallback

                if date_elem is not None:
                    try:
                        pub_date_str = date_elem.text
                        # Parse ISO 8601 (Atom) or RFC 2822 (RSS) formats
                        pub_date = None

                        if format_type == 'Atom':
                            # Atom uses ISO 8601: 2026-02-05T20:56:48.289Z
                            try:
                                # Try parsing with timezone
                                pub_date = datetime.fromisoformat(pub_date_str.replace('Z', '+00:00'))
                            except ValueError:
                                # Try without microseconds
                                try:
                                    pub_date = datetime.fromisoformat(pub_date_str.split('.')[0] + '+00:00')
                                except ValueError:
                                    pass
                        else:
                            # RSS uses RFC 2822
                            for fmt in [
                                '%a, %d %b %Y %H:%M:%S %Z',
                                '%a, %d %b %Y %H:%M:%S %z',
                                '%a, %d %b %Y %H:%M:%S GMT',
                            ]:
                                try:
                                    pub_date = datetime.strptime(pub_date_str, fmt)
                                    if pub_date.tzinfo is None:
                                        pub_date = pub_date.replace(tzinfo=timezone.utc)
                                    break
                                except ValueError:
                                    continue

                        if pub_date:
                            if latest_date is None or pub_date > latest_date:
                                latest_date = pub_date
                                latest_item = item
                    except Exception as e:
                        continue

            # Fallback: if no date found, use first item
            if latest_item is None:
                print(f"No date found, using first item")
                latest_item = items[0]
            else:
                # Check if the email is recent enough
                age_minutes = (datetime.now(timezone.utc) - latest_date).total_seconds() / 60
                print(f"Latest email from: {latest_date.strftime('%Y-%m-%d %H:%M:%S UTC')} ({age_minutes:.1f} minutes ago)")

                if age_minutes > max_age_minutes:
                    print(f"Latest email is too old ({age_minutes:.1f} min > {max_age_minutes} min)")
                    if attempt < max_retries:
                        wait_time = 10
                        print(f"Waiting {wait_time}s for new email...")
                        time.sleep(wait_time)
                    else:
                        print("Using older email as fallback (may be wrong passcode)")
                    continue

            # Get the content which contains the email body
            content = None

            if format_type == 'Atom':
                # Try <content> tag
                content_elem = latest_item.find(content_tag)
                if content_elem is not None:
                    content = content_elem.text
                # Try <summary> as fallback
                if not content and summary_tag:
                    summary_elem = latest_item.find(summary_tag)
                    if summary_elem is not None:
                        content = summary_elem.text
            else:
                # RSS format
                description = latest_item.find('description')
                if description is not None:
                    content = description.text
                # Try encoded content format
                if not content:
                    encoded = latest_item.find(RSS_CONTENT_NS + 'encoded')
                    if encoded is not None:
                        content = encoded.text

            if content:
                # Decode HTML entities (&lt; -> <, &gt; -> >, &quot; -> ")
                import html
                content = html.unescape(content)

                # Look for 6-digit passcode pattern
                passcode_match = re.search(r'\b(\d{6})\b', content)
                if passcode_match:
                    passcode = passcode_match.group(1)
                    print(f"Found passcode: {passcode}")
                    return passcode
                else:
                    print(f"Attempt {attempt}/{max_retries}: No 6-digit passcode found in email")
                    print(f"Content preview: {content[:300]}...")
            else:
                print(f"Attempt {attempt}/{max_retries}: No content found in feed item")

            # If we got here but didn't find passcode, wait and retry
            if attempt < max_retries:
                wait_time = 10
                print(f"Waiting {wait_time}s before retry...")
                time.sleep(wait_time)

        except requests.RequestException as e:
            print(f"Attempt {attempt}/{max_retries}: Error fetching feed: {e}")
            if attempt < max_retries:
                wait_time = 10
                print(f"Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
        except ET.ParseError as e:
            print(f"Attempt {attempt}/{max_retries}: Error parsing feed: {e}")
            if attempt < max_retries:
                time.sleep(10)
        except Exception as e:
            print(f"Attempt {attempt}/{max_retries}: Unexpected error: {e}")
            if attempt < max_retries:
                time.sleep(10)

    print("Failed to retrieve passcode after all retries")
    return None

class WSRef:
    """Wrapper for websocket that allows updating the underlying connection"""
    def __init__(self, ws):
        self.ws = ws

    def send(self, data):
        return self.ws.send(data)

    def recv(self):
        return self.ws.recv()

    def settimeout(self, timeout):
        self.ws.settimeout(timeout)

    def close(self):
        if self.ws:
            self.ws.close()

    def update(self, new_ws):
        """Update the underlying websocket connection"""
        self.ws = new_ws

def reconnect_websocket():
    """Reconnect to Chrome websocket, returns WSRef wrapper"""
    import websocket
    print("Reconnecting to Chrome...")
    try:
        ws_response = requests.get('http://localhost:9222/json', timeout=10)
        pages = ws_response.json()

        ws_url = None
        for page in pages:
            if page.get('type') == 'page':
                ws_url = page['webSocketDebuggerUrl']
                break

        if not ws_url:
            print("Could not find Chrome page for reconnection")
            return None

        raw_ws = websocket.create_connection(ws_url)
        raw_ws.send(json.dumps({'id': 1, 'method': 'Runtime.enable'}))
        raw_ws.recv()
        raw_ws.send(json.dumps({'id': 2, 'method': 'Network.enable'}))
        raw_ws.recv()
        print("Reconnected to Chrome")
        return WSRef(raw_ws)
    except Exception as e:
        print(f"Failed to reconnect: {e}")
        return None

def run_js(ws, script, timeout=10, retries=2):
    """Run JavaScript in Chrome with automatic reconnection

    ws: WSRef wrapper that can be updated when reconnecting
    Returns: result dict
    """
    global message_id

    for attempt in range(retries):
        try:
            # Check if websocket is still connected
            if ws.ws is None:
                new_ws_ref = reconnect_websocket()
                if new_ws_ref is None:
                    return {'error': 'Failed to reconnect'}
                ws.update(new_ws_ref.ws)

            message_id += 1
            current_id = message_id

            ws.send(json.dumps({
                'id': current_id,
                'method': 'Runtime.evaluate',
                'params': {'expression': script, 'awaitPromise': True, 'returnByValue': True}
            }))
            ws.settimeout(timeout)

            # Keep receiving until we get our response
            while True:
                result = ws.recv()
                data = json.loads(result)
                # Check if this is our response
                if data.get('id') == current_id:
                    return data
                # Otherwise it's an unrelated event, ignore and continue

        except (websocket.WebSocketConnectionClosedException, BrokenPipeError, ConnectionResetError) as e:
            print(f"WebSocket connection lost (attempt {attempt + 1}/{retries}): {e}")
            new_ws_ref = reconnect_websocket()
            if new_ws_ref is None:
                if attempt == retries - 1:
                    return {'error': f'Connection lost and reconnection failed: {e}'}
            else:
                ws.update(new_ws_ref.ws)
        except Exception as e:
            print(f"Error running JavaScript (attempt {attempt + 1}/{retries}): {e}")
            if attempt == retries - 1:
                return {'error': f'Failed to get response: {e}'}

    return {'error': 'Failed to get response after retries'}


def get_js_value(result):
    """Extract a returnByValue result from Chrome DevTools Runtime.evaluate."""
    if not isinstance(result, dict):
        return None
    inner = result.get('result', {})
    if not isinstance(inner, dict):
        return None
    runtime_result = inner.get('result', {})
    if not isinstance(runtime_result, dict):
        return None
    return runtime_result.get('value')

def fill_passcode(ws, passcode, max_submit_attempts=3):
    """Fill in the passcode and submit with multiple fallback strategies

    Args:
        ws: WebSocket connection to Chrome
        passcode: 6-digit passcode to enter
        max_submit_attempts: Maximum attempts to find and click submit button

    Returns:
        Dict with success status and details
    """
    print(f"Filling in passcode: {passcode}")

    # AGGRESSIVE cookie consent dismissal - try multiple times
    print("Aggressively dismissing cookie consent modals...")
    for i in range(3):
        dismiss_result = dismiss_cookie_consent(ws)
        if dismiss_result.get('dismissed'):
            print(f"Cookie consent dismissed (attempt {i+1})")
        time.sleep(0.5)

    # Also try clicking on the main page body to close any popovers
    click_body_script = """
    (function() {
        // Click on the main content area to close any overlays
        const main = document.querySelector('main, [role="main"], .main-content, body');
        if (main) {
            // Try to click somewhere that won't trigger a link
            main.click();
            return {clicked: true};
        }
        return {clicked: false};
    })()
    """
    run_js(ws, click_body_script)
    time.sleep(0.5)

    passcode_script = """
    (function() {
        // Look for passcode input - could be type="text" with placeholder
        const selectors = [
            'input[type="text"]',
            'input[name*="code" i]',
            'input[name*="passcode" i]',
            'input[placeholder*="code" i]',
            'input[placeholder*="passcode" i]',
            'input[id*="code" i]',
            'input[id*="passcode" i]',
        ];

        let passcodeInput = null;
        for (const selector of selectors) {
            passcodeInput = document.querySelector(selector);
            if (passcodeInput) break;
        }

        if (!passcodeInput) {
            const allInputs = Array.from(document.querySelectorAll('input'));
            return {success: false, error: 'Passcode input not found', inputCount: allInputs.length, inputTypes: allInputs.map(i => ({type: i.type, name: i.name, id: i.id, placeholder: i.placeholder}))};
        }

        passcodeInput.focus();

        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        nativeInputValueSetter.call(passcodeInput, '""" + passcode + """');

        const events = ['input', 'change', 'keyup', 'keydown', 'blur'];
        events.forEach(eventType => {
            const event = new Event(eventType, {bubbles: true, cancelable: true});
            passcodeInput.dispatchEvent(event);
        });

        return {success: true, inputFound: true, inputPlaceholder: passcodeInput.placeholder};
    })()
    """

    fill_result = run_js(ws, passcode_script, timeout=15)

    if not fill_result or fill_result.get('error'):
        print(f"Failed to fill passcode: {fill_result}")
        return {'success': False, 'error': 'Failed to fill passcode'}

    # Wait a bit for form validation
    time.sleep(1.5)

    # Try multiple submission strategies
    for attempt in range(max_submit_attempts):
        print(f"Submit attempt {attempt + 1}/{max_submit_attempts}...")

        submit_script = """
        (function() {
            // Get all visible buttons for debugging
            const allButtons = Array.from(document.querySelectorAll('button'))
                .filter(b => b.offsetParent !== null)
                .map(b => b.textContent.trim());

            // Strategy 1: Look for "Sign in" button (this is what ITV uses for passcode submit)
            const buttons = Array.from(document.querySelectorAll('button'));
            for (let btn of buttons) {
                if (btn.offsetParent === null) continue;
                const text = btn.textContent.trim();

                // Skip cookie consent buttons
                const parentText = btn.parentElement?.textContent.toLowerCase() || '';
                const closestSection = btn.closest('section, div[class*="cookie"], div[class*="consent"]');

                if (closestSection || parentText.includes('cookie') || parentText.includes('consent') ||
                    text === 'Accept' || text === 'Reject' || text === 'Manage' ||
                    text.includes('Cookie') || text.includes('Legitimate Interest')) {
                    continue;
                }

                // Look for Sign in button (ITV uses this for passcode submission)
                if (text === 'Sign in' || text === 'SIGN IN' || text === 'Continue' || text === 'CONTINUE') {
                    if (btn.disabled) btn.disabled = false;
                    btn.click();
                    return {success: true, method: 'text', text: text};
                }
            }

            // Strategy 2: Try any enabled submit button near the passcode input
            const passcodeInput = document.querySelector('input[type="text"], input[name*="code" i]');
            if (passcodeInput) {
                const form = passcodeInput.closest('form');
                const candidateButtons = Array.from(document.querySelectorAll('button, input[type="submit"]'))
                    .filter(el => el.offsetParent !== null && !el.disabled);
                const submitButton = candidateButtons.find(el => {
                    const text = (el.textContent || el.value || '').trim().toLowerCase();
                    if (text.includes('accept') || text.includes('reject') || text.includes('cookie') || text.includes('manage')) {
                        return false;
                    }
                    return el.type === 'submit' || text.includes('sign in') || text.includes('continue') || text.includes('submit');
                });
                if (submitButton) {
                    submitButton.scrollIntoView({block: 'center'});
                    submitButton.focus();
                    submitButton.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true, view: window}));
                    submitButton.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, cancelable: true, view: window}));
                    submitButton.click();
                    return {success: true, method: 'button_click', text: (submitButton.textContent || submitButton.value || '').trim()};
                }

                // Strategy 3: Ask the browser to submit the form as if the user clicked submit.
                if (form) {
                    if (form.requestSubmit) {
                        form.requestSubmit();
                        return {success: true, method: 'requestSubmit'};
                    }
                }

                // Strategy 4: Try pressing Enter on the input
                passcodeInput.focus();
                const enterEvent = new KeyboardEvent('keydown', {
                    key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true, cancelable: true
                });
                passcodeInput.dispatchEvent(enterEvent);
                return {success: true, method: 'enter_key'};
            }

            return {success: false, error: 'No submit method found', visibleButtons: allButtons.slice(0, 15)};
        })()
        """

        submit_result = run_js(ws, submit_script, timeout=10)

        value = get_js_value(submit_result)
        if isinstance(value, dict) and value.get('success'):
            print(f"Submit succeeded: {value}")
            return {'success': True, 'method': value.get('method', 'unknown')}
        print(f"Submit result: {value or submit_result}")

        # Wait before retry
        if attempt < max_submit_attempts - 1:
            print("Submit failed, trying to dismiss cookies again...")
            dismiss_cookie_consent(ws)
            time.sleep(1)

    # All attempts failed - log page state for debugging
    print("All submit attempts failed, logging page state...")
    log_page_state(ws, context="after failed passcode submit")

    return {'success': False, 'error': 'Failed to submit passcode after all attempts'}

def validate_page_state(ws):
    """Check if page is in a valid state before proceeding

    Args:
        ws: WebSocket connection to Chrome

    Returns:
        Dict with validation results: hasError, blockingModal, hasAccessibleInputs, etc.
    """
    validation_script = """
    (function() {
        // Check for error states
        const errorIndicators = [
            'something went wrong',
            'error occurred',
            'page not found',
            'service unavailable',
            'try again later',
            'page load error'
        ];

        const pageText = document.body.textContent.toLowerCase();
        const hasError = errorIndicators.some(indicator =>
            pageText.includes(indicator)
        );

        // Check if modal is blocking
        const modals = document.querySelectorAll('[role="dialog"], .modal, .popup, [class*="cookie"], [id*="cookie"]');
        const blockingModal = Array.from(modals).some(m =>
            m.offsetParent !== null && m.textContent.toLowerCase().includes('cookie')
        );

        // Check if form inputs are accessible
        const inputs = document.querySelectorAll('input[type="email"], input[type="password"], input[type="text"]');
        const hasAccessibleInputs = Array.from(inputs).some(i =>
            i.offsetParent !== null
        );

        // Get visible buttons for debugging
        const visibleButtons = Array.from(document.querySelectorAll('button'))
            .filter(b => b.offsetParent !== null)
            .map(b => b.textContent.trim())
            .slice(0, 15);

        return {
            hasError,
            blockingModal,
            hasAccessibleInputs,
            modalCount: modals.length,
            inputCount: inputs.length,
            visibleButtons: visibleButtons,
            url: window.location.href
        };
    })()
    """
    result = run_js(ws, validation_script, timeout=10)
    if result and 'result' in result:
        inner_result = result.get('result', {})
        if isinstance(inner_result, dict) and 'value' in inner_result:
            return inner_result.get('value', {})
    return {}

def extract_jwt_exp(token):
    """Extract JWT expiration timestamp from token."""
    try:
        if not token or not token.startswith('eyJ'):
            return None
        parts = token.split('.')
        if len(parts) >= 2:
            import base64
            payload = parts[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += '=' * padding
            decoded = base64.urlsafe_b64decode(payload)
            data = json.loads(decoded)
            if 'exp' in data:
                return data['exp']
    except Exception:
        pass
    return None


def start_chrome_and_login(email, password):
    """Start Chrome and log in like a human user"""
    global temp_profile

    print("Starting Chrome...")
    log_automation_event('automation_chrome_start', {'email': email})

    subprocess.run(['pkill', '-9', 'chromium'], stderr=subprocess.DEVNULL)
    time.sleep(3)

    # Clean up any old temp profiles first
    import glob
    old_profiles = glob.glob('/tmp/chrome_itv_*')
    for old_profile in old_profiles:
        try:
            shutil.rmtree(old_profile, ignore_errors=True)
        except:
            pass

    # Use a fresh profile each time to avoid ITV fingerprinting
    temp_profile = tempfile.mkdtemp(prefix='chrome_itv_')
    print(f"Using temp profile: {temp_profile}")

    chrome_cmd = [
        'chromium',
        '--no-sandbox',
        '--disable-gpu',
        '--disable-dev-shm-usage',
        '--remote-debugging-port=9222',
        '--remote-allow-origins=*',
        '--user-data-dir=' + temp_profile,
        '--disable-web-security',
        '--disable-features=VizDisplayCompositor',
        '--disable-extensions',
        '--disable-background-networking',
        '--disable-default-apps',
        '--disable-sync',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-blink-features=AutomationControlled',
        # More anti-detection flags
        '--exclude-switches=enable-automation',
        '--disable-infobars',
        '--window-size=1920,1080',
        '--start-maximized',
        '--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        # Disable more fingerprinting vectors
        '--disable-webrtc',
        '--disable-webgl',
        '--disable-software-rasterizer',
        'about:blank'
    ]

    subprocess.Popen(chrome_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )

    print("Waiting for Chrome to load...")
    random_delay(10, 14)

    import websocket
    ws_response = requests.get('http://localhost:9222/json', timeout=15)
    pages = ws_response.json()

    ws_url = None
    for page in pages:
        if page.get('type') == 'page':
            ws_url = page['webSocketDebuggerUrl']
            break

    if not ws_url:
        print("Could not connect to Chrome")
        log_automation_event('automation_chrome_failed', {'error': 'Could not find Chrome page'}, severity='error')
        return None

    print("Connected to Chrome")
    ws = WSRef(websocket.create_connection(ws_url))

    ws.send(json.dumps({'id': 1, 'method': 'Runtime.enable'}))
    ws.recv()

    # Enable Network for cookie operations
    ws.send(json.dumps({'id': 2, 'method': 'Network.enable'}))
    ws.recv()

    print("Clearing ALL cookies (including tracking cookies)...")

    # Get all cookies first to see what we're clearing
    ws.send(json.dumps({'id': 3, 'method': 'Network.getCookies'}))
    cookie_result = ws.recv()

    # Clear ALL browser cookies multiple times to be sure
    for i in range(3):
        ws.send(json.dumps({'id': 4 + i, 'method': 'Network.clearBrowserCookies'}))
        ws.recv()
        time.sleep(0.5)

    # Also use Storage API to clear ALL data (not just ITV)
    ws.send(json.dumps({'id': 10, 'method': 'Storage.enable'}))
    ws.recv()

    # Clear ALL storage for all origins we can find
    ws.send(json.dumps({'id': 11, 'method': 'Storage.getUsageAndQuota'}))
    ws.recv()

    # Clear data for EVERYTHING - not just ITV
    origins_to_clear = [
        'https://www.itv.com',
        'https://itv.com',
        'http://www.itv.com',
        'http://itv.com',
        'https://www.googletagmanager.com',
        'https://google-analytics.com',
        'https://www.google-analytics.com',
        'https://analytics.google.com',
        'https://connect.facebook.net',
        'https://bat.bing.com',
        'https://doubleclick.net',
        'https://www.doubleclick.net',
        'https://js.hs-scripts.com',
        'https://js.hs-analytics.net',
    ]

    msg_id = 12
    for origin in origins_to_clear:
        ws.send(json.dumps({
            'id': msg_id,
            'method': 'Storage.clearDataForOrigin',
            'params': {'origin': origin, 'storageTypes': 'all'}
        }))
        ws.recv()
        msg_id += 1

    # Clear ALL cache storage
    print("Clearing all cache storage...")
    ws.send(json.dumps({'id': 50, 'method': 'Network.clearBrowserCache'}))
    ws.recv()

    # Clear service workers
    print("Unregistering service workers...")
    unregister_sw_script = """
    (async function() {
        if ('serviceWorker' in navigator) {
            const registrations = await navigator.serviceWorker.getRegistrations();
            for (let registration of registrations) {
                await registration.unregister();
            }
            return {unregistered: registrations.length};
        }
        return {unregistered: 0};
    })()
    """
    run_js(ws, unregister_sw_script)

    # Clear indexedDB
    print("Clearing IndexedDB...")
    clear_idb_script = """
    (async function() {
        const databases = await indexedDB.databases();
        for (const db of databases) {
            if (db.name) {
                indexedDB.deleteDatabase(db.name);
            }
        }
        return {cleared: databases.length};
    })()
    """
    run_js(ws, clear_idb_script)

    # Clear storage
    print("Clearing local/session storage...")
    clear_storage_script = """
    (function() {
        localStorage.clear();
        sessionStorage.clear();
        return {cleared: true};
    })()
    """
    run_js(ws, clear_storage_script)

    # Hide automation indicators
    print("Hiding automation traces...")
    hide_automation_script = """
    (function() {
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['en-GB', 'en', 'en-US']});
        window.chrome = {runtime: {}};
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        return {hidden: true};
    })()
    """
    run_js(ws, hide_automation_script)

    # NEW APPROACH: Start at homepage like a real user
    print("Navigating to ITV homepage (like a real user)...")
    ws.send(json.dumps({
        'id': msg_id,
        'method': 'Page.navigate',
        'params': {'url': 'https://www.itv.com/watch'}
    }))

    print("Waiting for page to load...")
    random_delay(8, 12)

    # Validate page state and check for errors
    print("Validating page state...")
    validation = validate_page_state(ws)
    if validation.get('hasError'):
        print(f"WARNING: Page has error state: {validation.get('visibleButtons', [])}")
    if validation.get('blockingModal'):
        print(f"WARNING: Blocking modal detected")

    # Dismiss cookie consent modal if present
    print("Checking for cookie consent modal...")
    dismiss_result = dismiss_cookie_consent(ws)
    if dismiss_result.get('dismissed'):
        print("Cookie consent dismissed, waiting for page to settle...")
        random_delay(1, 2)

    # Log page state for debugging
    log_page_state(ws, context="after page load")

    # Now click the Sign in button like a human would
    print("Looking for Sign in button...")
    click_signin_script = """
    (function() {
        // Look for sign in button/link
        const signinSelectors = [
            'a[href*="signin"]',
            'a[href*="login"]',
            'button[data-testid="signInButton"]',
            'a:has-text("Sign in")',
            'button:has-text("Sign in")',
        ];

        for (const selector of signinSelectors) {
            try {
                const element = document.querySelector(selector);
                if (element) {
                    element.click();
                    return {success: true, selector: selector, text: element.textContent};
                }
            } catch (e) {}
        }

        // Try by text content
        const links = Array.from(document.querySelectorAll('a'));
        for (const link of links) {
            const text = link.textContent.trim().toLowerCase();
            if (text === 'sign in' || text === 'signin') {
                link.click();
                return {success: true, selector: 'text', text: link.textContent};
            }
        }

        return {success: false, error: 'Sign in link not found', totalLinks: links.length};
    })()
    """

    result = run_js(ws, click_signin_script)
    print("Click sign-in result:", result)

    # Wait for navigation to login page
    print("Waiting for login page to load...")
    random_delay(10, 15)

    # Log page state after login page load
    log_page_state(ws, context="after login page load")

    # Step 1: Fill in email
    print("Waiting for email form...")
    random_delay(1, 3)

    print("Filling in email...")
    email_script = """
    (function() {
        const emailInput = document.querySelector('input[type="email"], input[name="email"]');
        if (!emailInput) {
            return {success: false, error: 'Email input not found'};
        }

        emailInput.focus();

        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        nativeInputValueSetter.call(emailInput, '""" + email + """');

        const events = ['input', 'change', 'keyup', 'keydown', 'blur', 'focus'];
        events.forEach(eventType => {
            const event = new Event(eventType, {bubbles: true, cancelable: true});
            emailInput.dispatchEvent(event);
        });

        return new Promise(resolve => {
            setTimeout(() => {
                const buttons = Array.from(document.querySelectorAll('button'));
                for (let btn of buttons) {
                    const text = btn.textContent.trim();
                    if (text.includes('CONTINUE') || text.includes('Continue') || text === 'CONTINUE') {
                        if (btn.disabled) {
                            resolve({success: false, error: 'Continue button is disabled', buttonText: text});
                        } else {
                            btn.click();
                            resolve({success: true, buttonText: text});
                        }
                        return;
                    }
                }
                resolve({success: false, error: 'Continue button not found'});
            }, 800);
        });
    })()
    """

    result = run_js(ws, email_script)
    print("Email step result:", result)

    # Log page state after email submission
    time.sleep(1)
    log_page_state(ws, context="after email submit")

    # Wait for password page - random delay
    print("Waiting for password page...")
    random_delay(12, 18)

    # Check if we got password page or passcode page
    check_page_script = """
    (function() {
        const passwordField = document.querySelector('input[type="password"]');
        const codeInput = document.querySelector('input[type="text"][placeholder*="code" i], input[type="text"][placeholder*="passcode" i]');
        const headings = Array.from(document.querySelectorAll('h1, h2, h3')).map(h => h.textContent);

        return {
            hasPasswordField: !!passwordField,
            hasCodeInput: !!codeInput,
            headings: headings
        };
    })()
    """

    page_check = run_js(ws, check_page_script)
    print("Page check:", page_check)

    # Parse the result to determine which flow to use
    # Structure: {'result': {'result': {'type': 'object', 'value': {...}}}}
    page_result = page_check.get('result', {})
    if isinstance(page_result, dict):
        page_result = page_result.get('result', page_result)
    if isinstance(page_result, dict) and 'value' in page_result:
        page_data = page_result.get('value', page_result)
    else:
        page_data = page_result

    has_password = page_data.get('hasPasswordField', False) if isinstance(page_data, dict) else False
    headings = page_data.get('headings', []) if isinstance(page_data, dict) else []

    print(f"Has password field: {has_password}")
    print(f"Headings: {headings}")

    # Determine login flow based on what we see
    if has_password:
        # PASSWORD FLOW - fill in the password
        print("PASSWORD DETECTED - Using password login flow...")
        log_automation_event('automation_password_flow', {'headings': headings})
        password_script = """
    (function() {
        const passwordField = document.querySelector('input[type="password"]');
        if (!passwordField) {
            // Try to find any input that might be password
            const allInputs = Array.from(document.querySelectorAll('input'));
            for (const input of allInputs) {
                if (input.type === 'password' || input.name.toLowerCase().includes('pass')) {
                    return {success: true, foundBy: 'search', input: input.name || input.type};
                }
            }
            return {success: false, error: 'Password field not found', inputTypes: allInputs.map(i => i.type)};
        }

        passwordField.focus();

        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        nativeInputValueSetter.call(passwordField, '""" + password + """');

        const events = ['input', 'change', 'keyup', 'keydown', 'blur'];
        events.forEach(eventType => {
            const event = new Event(eventType, {bubbles: true, cancelable: true});
            passwordField.dispatchEvent(event);
        });

        return new Promise(resolve => {
            setTimeout(() => {
                let submitButton = document.querySelector('button[data-testid="signInButton"]');
                if (!submitButton) {
                    const buttons = Array.from(document.querySelectorAll('button'));
                    for (let btn of buttons) {
                        const text = btn.textContent.trim();
                        if (text.includes('Sign in') || text.includes('SIGN IN') || text === 'Sign in') {
                            submitButton = btn;
                            break;
                        }
                    }
                }
                if (!submitButton) {
                    resolve({success: false, error: 'Submit button not found'});
                    return;
                }

                if (submitButton.disabled) {
                    submitButton.disabled = false;
                    submitButton.click();
                    resolve({success: true, note: 'Force-enabled disabled button'});
                    return;
                }

                submitButton.click();
                resolve({success: true, buttonText: submitButton.textContent.trim()});
            }, 1000);
        });
    })()
    """

        result = run_js(ws, password_script, timeout=20)
        print("Password step result:", result)

        # Log page state after password submission
        time.sleep(1)
        log_page_state(ws, context="after password submit")
    else:
        # PASSCODE FLOW - retrieve passcode from RSS and fill it
        print("PASSCODE DETECTED - Using passcode login flow...")
        log_automation_event('automation_passcode_flow', {'headings': headings}, severity='warning')
        print("Waiting 45s for email to arrive at kill-the-newsletter...")
        print("(Passcode is valid for 15 minutes, so we can afford to wait)")
        time.sleep(45)  # Fixed 45s wait + 20s in get_passcode_from_rss = ~65s total

        # RSS feed URL for kill-the-newsletter
        rss_feed_url = "https://kill-the-newsletter.com/feeds/562bcygvohfpdf273h96.xml"

        passcode = get_passcode_from_rss(rss_feed_url)
        if passcode:
            result = fill_passcode(ws, passcode)
            print("Passcode step result:", result)
        else:
            print("ERROR: Could not retrieve passcode from RSS feed")
            ws.close()
            return None

    ws.close()

    print("Waiting for login to complete...")
    for i in range(10):
        random_delay(1.5, 2.5)

    return extract_token_from_chrome()

def extract_token_from_chrome():
    """Extract token from Chrome cookies"""
    import websocket

    ws_response = requests.get('http://localhost:9222/json', timeout=10)
    pages = ws_response.json()

    ws_url = None
    for page in pages:
        if page.get('type') == 'page':
            if 'itv.com' in page.get('url', ''):
                ws_url = page['webSocketDebuggerUrl']
                break
            if not ws_url:
                ws_url = page['webSocketDebuggerUrl']

    if not ws_url:
        print("Could not connect to Chrome")
        return None

    ws = websocket.create_connection(ws_url)
    ws.send(json.dumps({'id': 1, 'method': 'Network.enable'}))
    ws.recv()

    ws.send(json.dumps({'id': 2, 'method': 'Network.getCookies'}))
    result = ws.recv()

    ws.close()

    data = json.loads(result)

    if 'result' in data and 'cookies' in data['result']:
        cookies = data['result']['cookies']

        for cookie in cookies:
            if 'itv.com' in cookie.get('domain', ''):
                name = cookie['name']
                val = cookie['value']

                if 'Session' in name:
                    try:
                        session = json.loads(val)
                        if 'tokens' in session and 'content' in session['tokens']:
                            access_token = session['tokens']['content'].get('access_token')
                            if access_token and access_token.startswith('eyJ'):
                                return access_token
                    except:
                        pass

    return None

def update_stack_env(token, env_file=None):
    if env_file is None:
        env_file = get_stack_env_path()
    print("Updating " + env_file + "...")
    if os.path.exists(env_file):
        with open(env_file, "r") as f:
            lines = f.readlines()
    else:
        lines = []
    updated = False
    for i, line in enumerate(lines):
        if line.startswith("ITV_ACCESS_TOKEN="):
            lines[i] = "ITV_ACCESS_TOKEN=" + token + "\n"
            updated = True
            break
    if not updated:
        lines.append("ITV_ACCESS_TOKEN=" + token + "\n")
    with open(env_file, "w") as f:
        f.writelines(lines)
    print("Token updated in stack.env")

def create_restart_marker():
    """Create a marker file to indicate this is an automation restart.

    The container will check for this file on startup and skip token refresh
    to prevent a restart loop.

    Marker is created in the app logs directory, which maps to /app/logs in container.
    """
    marker_path = os.path.join(get_logs_dir(), ".automation_restart")
    try:
        # Ensure logs directory exists
        os.makedirs(os.path.dirname(marker_path), exist_ok=True)
        with open(marker_path, 'w') as f:
            f.write(str(time.time()))
        print(f"Created restart marker: {marker_path}")
        return True
    except Exception as e:
        print(f"Warning: Could not create restart marker: {e}")
        return False


def update_docker_container_env(token):
    """Update the token and restart the container.

    This is a simpler approach that:
    1. Updates stack.env with the new token
    2. Creates a restart marker to prevent startup refresh loop
    3. Restarts the container

    The container will read the new token from stack.env on startup.
    """
    print("Preparing container restart with new token...")

    # Find the ITV container
    result = subprocess.run(
        ["docker", "ps", "--filter", "name=itv", "--format", "{{.Names}}"],
        capture_output=True,
        text=True
    )
    container_name = result.stdout.strip()

    if not container_name:
        print("Warning: Could not find ITV container")
        return False

    # Create the restart marker BEFORE restarting
    # This file will be checked by the container on startup
    create_restart_marker()

    try:
        print(f"Restarting container {container_name}...")
        subprocess.run(["docker", "restart", container_name], check=True)
        print(f"Container {container_name} restarted successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error restarting container: {e}")
        return False

def cleanup():
    global temp_profile
    print("Closing Chrome...")
    subprocess.run(['pkill', '-9', 'chromium'], stderr=subprocess.DEVNULL)
    if temp_profile and os.path.exists(temp_profile):
        print(f"Removing temp profile: {temp_profile}")
        shutil.rmtree(temp_profile, ignore_errors=True)

def getenv(var_name, default=''):
    """Get environment variable from os.environ or stack.env file."""
    # First check os.environ (set by Portainer/Docker)
    value = os.environ.get(var_name)
    if value:
        return value

    # Fallback: read from stack.env file
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    stack_env_path = os.path.join(parent_dir, 'stack.env')

    if os.path.exists(stack_env_path):
        with open(stack_env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith(f'{var_name}='):
                    return line.split('=', 1)[1].strip()

    return default

def main():
    print("=" * 50)
    print("ITVX Password Login (Chrome Automation)")
    print("=" * 50)

    os.environ.setdefault('DISPLAY', ':1')

    # Read credentials from environment (stack.env or Portainer)
    email = getenv('ITVX_EMAIL')
    password = getenv('ITVX_PASSWORD')

    if not email or not password:
        print("ERROR: ITVX_EMAIL and ITVX_PASSWORD must be set in stack.env or as environment variables")
        print(f"Add the following to {get_stack_env_path()}:")
        print("  ITVX_EMAIL=your@email.com")
        print("  ITVX_PASSWORD=yourpassword")
        log_automation_event('credentials_missing', {
            'has_email': bool(email),
            'has_password': bool(password)
        }, severity='critical')
        sys.exit(1)

    # Log start of token refresh attempt
    log_automation_event('token_refresh_start', {
        'email': email[:email.find('@')] + '@...' if '@' in email else 'unknown',
        'max_attempts': 3
    })

    # Retry entire login flow up to 3 times with exponential backoff
    max_login_attempts = 3
    access_token = None
    last_error = None

    for attempt in range(max_login_attempts):
        if attempt > 0:
            wait_time = exponential_backoff(attempt - 1, base_delay=30, max_delay=300)
            print(f"\n{'=' * 50}")
            print(f"RETRYING LOGIN (attempt {attempt + 1}/{max_login_attempts})")
            print(f"Waiting {wait_time:.1f}s before retry...")
            if last_error:
                print(f"Last error: {last_error}")
            print(f"{'=' * 50}\n")

            log_automation_event('automation_retry', {
                'attempt': attempt + 1,
                'max_attempts': max_login_attempts,
                'wait_time_seconds': wait_time,
                'previous_error': last_error
            }, severity='warning')

            time.sleep(wait_time)

        try:
            access_token = start_chrome_and_login(email, password)

            if access_token:
                print("\n" + "=" * 50)
                print("SUCCESS!")
                print("=" * 50)
                print("Token: " + access_token[:100] + "...")

                # Extract JWT expiration for logging
                jwt_exp = extract_jwt_exp(access_token)

                log_automation_event('automation_login_success', {
                    'attempt': attempt + 1,
                    'token_prefix': access_token[:20],
                    'jwt_expiration': jwt_exp
                })

                log_automation_event('token_refresh_success', {
                    'attempts': attempt + 1,
                    'jwt_expiration': jwt_exp
                })

                # Update stack.env file (for reference/redundancy)
                update_stack_env(access_token)

                # Update the Docker container's environment directly
                # This recreates the container with the new token baked in
                update_docker_container_env(access_token)

                log_automation_event('container_restart', {'trigger': 'token_refresh'})

                break
            else:
                print(f"\nLogin attempt {attempt + 1}/{max_login_attempts} failed")
                last_error = "No token returned from login function"

                log_automation_event('automation_login_failed', {
                    'attempt': attempt + 1,
                    'error': last_error
                }, severity='error')

        except Exception as e:
            print(f"\nLogin attempt {attempt + 1}/{max_login_attempts} raised exception: {e}")
            last_error = str(e)
            import traceback
            traceback.print_exc()

            log_automation_event('automation_login_failed', {
                'attempt': attempt + 1,
                'error': last_error,
                'exception_type': type(e).__name__
            }, severity='error')

    if not access_token:
        print("\n" + "=" * 50)
        print("ALL LOGIN ATTEMPTS FAILED")
        print("=" * 50)
        print("Check logs for details")

        log_automation_event('token_refresh_failed', {
            'total_attempts': max_login_attempts,
            'final_error': last_error
        }, severity='critical')

        return

    print("\nDone! Your streams should be working now.")

if __name__ == "__main__":
    main()
