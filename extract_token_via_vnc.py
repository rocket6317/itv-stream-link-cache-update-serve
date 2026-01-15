#!/usr/bin/env python3
"""
ITV Token Extractor via VNC
Extracts JWT token from Chrome using Chrome DevTools Protocol
"""

import subprocess
import time
import websocket
import json
import requests
import os
from datetime import datetime, timezone

LOG_FILE = '/home/dietpi/itv/token_refresh.log'
MAX_LOG_ENTRIES = 500
STACK_ENV = '/home/dietpi/itv/stack.env'

def load_env_file(env_path=STACK_ENV):
    """Load environment variables from a file without requiring dotenv."""
    env_vars = {}
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                # Parse KEY=VALUE
                if '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    return env_vars

# Load env vars at module level for easy access
ENV_VARS = load_env_file()

def getenv(key, default=None):
    """Get environment variable from both os.environ and our loaded env file."""
    return os.getenv(key, ENV_VARS.get(key, default))

def log_event(event_type, message):
    """Log an event to the token refresh log file."""
    log_entry = {
        'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'event': event_type,
        'message': message
    }

    # Read existing logs
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    logs = json.loads(content)
        except:
            pass

    # Add new entry
    logs.append(log_entry)

    # Keep only last MAX_LOG_ENTRIES
    if len(logs) > MAX_LOG_ENTRIES:
        logs = logs[-MAX_LOG_ENTRIES:]

    # Write back
    with open(LOG_FILE, 'w') as f:
        json.dump(logs, f, indent=2)

def wait_for_chrome_debug_port(timeout=60):
    """Wait for Chrome debug port to respond with page list."""
    print("Waiting for Chrome debug port...", end='', flush=True)
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            response = requests.get('http://localhost:9222/json', timeout=2)
            pages = response.json()

            if pages and len(pages) > 0:
                elapsed = int(time.time() - start_time)
                print(f" OK! ({elapsed}s)")
                log_event("chrome_ready", f"Chrome debug port ready in {elapsed}s")
                return True
        except requests.exceptions.RequestException:
            pass

        print(".", end='', flush=True)
        time.sleep(1)

    print(" TIMEOUT!")
    log_event("chrome_timeout", f"Chrome debug port timeout after {timeout}s")
    return False

def wait_for_itv_page(timeout=60):
    """Wait for ITV page to load and appear in page list."""
    print("Waiting for ITV page...", end='', flush=True)
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            response = requests.get('http://localhost:9222/json', timeout=2)
            pages = response.json()

            for page in pages:
                if 'itv.com' in page.get('url', ''):
                    elapsed = int(time.time() - start_time)
                    print(f" OK! ({elapsed}s)")
                    log_event("page_loaded", f"ITV page loaded in {elapsed}s")
                    return True
        except requests.exceptions.RequestException:
            pass

        print(".", end='', flush=True)
        time.sleep(1)

    print(" TIMEOUT!")
    log_event("page_timeout", f"ITV page timeout after {timeout}s")
    return False

def start_chrome():
    """Start Chrome with remote debugging enabled."""
    print("Starting Chrome...")

    # Kill any existing Chrome
    subprocess.run(['pkill', '-9', 'chromium'], stderr=subprocess.DEVNULL)

    time.sleep(2)

    # Start Chrome with debug port
    chrome_cmd = [
        'chromium',
        '--no-sandbox',
        '--disable-gpu',
        '--disable-dev-shm-usage',
        '--remote-debugging-port=9222',
        '--remote-allow-origins=*',
        '--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'https://www.itv.com/watch'
    ]

    subprocess.Popen(chrome_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )

    # Wait for Chrome to actually be ready (not just sleep)
    if not wait_for_chrome_debug_port(timeout=30):
        print("ERROR: Chrome debug port did not respond")
        return False

    if not wait_for_itv_page(timeout=30):
        print("ERROR: ITV page did not load")
        return False

    print("Chrome started and page loaded")
    return True

def is_token_expired(token):
    """Check if token is expired or close to expiry."""
    if not token or not token.startswith('eyJ'):
        return True, 0

    try:
        import base64
        parts = token.split('.')
        if len(parts) >= 2:
            payload = parts[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += '=' * padding
            decoded = base64.urlsafe_b64decode(payload)
            data = json.loads(decoded)

            if 'exp' in data:
                exp_timestamp = data['exp']
                # Make exp_date timezone-aware (UTC)
                exp_date = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
                now = datetime.now(timezone.utc)
                hours_remaining = (exp_date - now).total_seconds() / 3600

                # Token is expired or has less than 2 hours
                if hours_remaining < 2:
                    return True, hours_remaining

                return False, hours_remaining
    except Exception as e:
        print(f"Error decoding token: {e}")
        return True, 0

    return True, 0

def extract_token():
    """Extract token via Chrome DevTools Protocol."""
    print("Connecting to Chrome...")

    # Get the target page
    response = requests.get('http://localhost:9222/json')
    pages = response.json()

    for page in pages:
        if 'itv.com' in page.get('url', ''):
            ws_url = page['webSocketDebuggerUrl']

            # Connect via WebSocket
            ws = websocket.create_connection(ws_url)

            # Enable Network domain
            ws.send(json.dumps({'id': 1, 'method': 'Network.enable'}))
            ws.recv()

            # Get all cookies
            ws.send(json.dumps({'id': 2, 'method': 'Network.getCookies'}))
            result = ws.recv()

            data = json.loads(result)
            ws.close()

            if 'result' in data and 'cookies' in data['result']:
                cookies = data['result']['cookies']

                for cookie in cookies:
                    if 'itv.com' in cookie.get('domain', ''):
                        name = cookie['name']
                        val = cookie['value']

                        # Check for JWT in Itv.Session
                        if 'Session' in name:
                            try:
                                session = json.loads(val)
                                if 'tokens' in session and 'content' in session['tokens']:
                                    access_token = session['tokens']['content'].get('access_token')
                                    if access_token and access_token.startswith('eyJ'):
                                        return access_token
                            except:
                                pass

                        # Check for direct JWT
                        if val.startswith('eyJ') and len(val) > 500:
                            return val

    return None

def clear_itv_cookies_and_refresh(ws):
    """Clear ITV cookies and navigate to login to force token refresh."""
    print("Clearing ITV cookies to force login...")

    # Clear all cookies for itv.com domain
    ws.send(json.dumps({
        'id': 10,
        'method': 'Network.clearBrowserCookies'
    }))
    ws.recv()

    # Navigate to login page directly
    ws.send(json.dumps({
        'id': 11,
        'method': 'Page.navigate',
        'params': {'url': 'https://www.itv.com/watch'}
    }))
    ws.recv()

    print("Navigated to ITV login page - waiting for fresh token...")

def auto_login_itv(ws, email, password):
    """Automatically fill and submit the ITVX login form."""
    print("Attempting auto-login...")

    # Enable Runtime and DOM domains
    ws.send(json.dumps({'id': 20, 'method': 'Runtime.enable'}))
    ws.recv()

    ws.send(json.dumps({'id': 21, 'method': 'DOM.enable'}))
    ws.recv()

    # Wait for page to be fully loaded
    time.sleep(3)

    # JavaScript to find and fill the login form
    login_script = """
    (function() {
        // Look for email input - try various selectors
        const emailSelectors = [
            'input[type="email"]',
            'input[name="email"]',
            'input[id*="email"]',
            'input[placeholder*="email" i]',
            '#email'
        ];

        const passwordSelectors = [
            'input[type="password"]',
            'input[name="password"]',
            'input[id*="password"]',
            '#password'
        ];

        let emailField = null;
        let passwordField = null;

        for (const selector of emailSelectors) {
            emailField = document.querySelector(selector);
            if (emailField) break;
        }

        for (const selector of passwordSelectors) {
            passwordField = document.querySelector(selector);
            if (passwordField) break;
        }

        if (!emailField || !passwordField) {
            return {success: false, error: 'Could not find login fields'};
        }

        // Focus and fill email
        emailField.focus();
        emailField.value = '%s';
        emailField.dispatchEvent(new Event('input', {bubbles: true}));
        emailField.dispatchEvent(new Event('change', {bubbles: true}));

        // Focus and fill password
        passwordField.focus();
        passwordField.value = '%s';
        passwordField.dispatchEvent(new Event('input', {bubbles: true}));
        passwordField.dispatchEvent(new Event('change', {bubbles: true}));

        // Look for submit button
        const submitSelectors = [
            'button[type="submit"]',
            'button[id*="submit" i]',
            'button[id*="login" i]',
            'button[id*="sign-in" i]',
            'button:contains("Sign in")',
            'button:contains("Log in")',
            'input[type="submit"]'
        ];

        for (const selector of submitSelectors) {
            const btn = document.querySelector(selector);
            if (btn) {
                btn.click();
                return {success: true, method: 'clicked_' + selector};
            }
        }

        // Try pressing Enter on password field
        passwordField.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
        passwordField.dispatchEvent(new KeyboardEvent('keyup', {key: 'Enter', bubbles: true}));

        return {success: true, method: 'enter_key'};
    })()
    """ % (email, password)

    # Execute the login script
    ws.send(json.dumps({
        'id': 22,
        'method': 'Runtime.evaluate',
        'params': {'expression': login_script, 'awaitPromise': True, 'returnByValue': True}
    }))

    result = ws.recv()
    data = json.loads(result)

    if 'result' in data and 'result' in data['result']:
        login_result = data['result']['result'].get('value', {})
        if login_result.get('success'):
            print(f"Login form submitted successfully")
            log_event("auto_login_success", f"Auto-login completed: {login_result.get('method')}")
            return True
        else:
            print(f"Auto-login failed: {login_result.get('error')}")
            log_event("auto_login_failed", login_result.get('error'))
            return False

    print("Could not determine login result")
    log_event("auto_login_unknown", "Could not determine login result")
    return False

def force_token_refresh():
    """Force a token refresh by clearing cookies, auto-login, and waiting for new token."""
    print("Forcing token refresh...")
    log_event("token_refresh_needed", "Extracted token expired, forcing refresh")

    # Get credentials from environment (checks both os.environ and stack.env file)
    email = getenv('ITVX_EMAIL') or getenv('ITV_EMAIL')
    password = getenv('ITVX_PASSWORD') or getenv('ITV_PASSWORD')

    if not email or not password:
        print("WARNING: ITVX_EMAIL and ITVX_PASSWORD not set in environment")
        print("Please add them to stack.env for automated login:")
        print("  ITVX_EMAIL=your@email.com")
        print("  ITVX_PASSWORD=yourpassword")
        log_event("credentials_missing", "ITVX_EMAIL or ITVX_PASSWORD not set")

    # Get the target page
    response = requests.get('http://localhost:9222/json')
    pages = response.json()

    for page in pages:
        if 'itv.com' in page.get('url', '') or 'itv' in page.get('url', ''):
            ws_url = page['webSocketDebuggerUrl']

            # Connect via WebSocket
            ws = websocket.create_connection(ws_url)

            # Enable required domains
            ws.send(json.dumps({'id': 1, 'method': 'Network.enable'}))
            ws.recv()

            ws.send(json.dumps({'id': 2, 'method': 'Page.enable'}))
            ws.recv()

            # Clear cookies and navigate to login page
            clear_itv_cookies_and_refresh(ws)

            # If credentials are available, attempt auto-login
            if email and password:
                time.sleep(5)  # Wait for login page to fully load
                auto_login_itv(ws, email, password)

            ws.close()
            break

    # Wait for login to complete and token to be available
    wait_time = 30 if email and password else 60
    print(f"Waiting {wait_time} seconds for login and new token...")
    log_event("waiting_for_login", f"Waiting {wait_time}s for login to complete")
    time.sleep(wait_time)

def update_stack_env(token):
    """Update stack.env with new token."""
    env_file = '/home/dietpi/itv/stack.env'

    print(f"Updating {env_file}...")

    # Read existing file
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            lines = f.readlines()
    else:
        lines = []

    # Update or add token
    updated = False
    for i, line in enumerate(lines):
        if line.startswith('ITV_ACCESS_TOKEN='):
            lines[i] = f'ITV_ACCESS_TOKEN={token}\n'
            updated = True
            break

    if not updated:
        lines.append(f'ITV_ACCESS_TOKEN={token}\n')

    # Write back
    with open(env_file, 'w') as f:
        f.writelines(lines)

    print(f"Token updated ({len(token)} chars)")

def restart_container():
    """Restart the ITV container."""
    print("Restarting container...")

    result = subprocess.run(
        ['docker', 'ps', '--filter', 'name=itv', '--format', '{{.Names}}'],
        capture_output=True,
        text=True
    )

    container_name = result.stdout.strip()
    if container_name:
        subprocess.run(['docker', 'restart', container_name])
        print(f"Container {container_name} restarted")
    else:
        print("Warning: Could not find ITV container")

def cleanup():
    """Close Chrome to free up resources."""
    print("Closing Chrome...")
    subprocess.run(['pkill', '-9', 'chromium'], stderr=subprocess.DEVNULL)
    print("Chrome closed")

def main():
    print("=" * 60)
    print("ITV Token Extractor via VNC")
    print("=" * 60)
    print()

    log_event("script_start", "Token extraction script started")

    # Reload env vars from stack.env in case they were updated
    global ENV_VARS
    ENV_VARS = load_env_file()

    # Make sure DISPLAY is set
    if not os.environ.get('DISPLAY'):
        os.environ['DISPLAY'] = ':1'

    # Start Chrome
    if not start_chrome():
        print()
        print("=" * 60)
        print("ERROR: Chrome failed to start properly")
        print("=" * 60)
        log_event("chrome_failed", "Chrome failed to start properly")
        return

    # Extract token with retry logic
    print("Extracting token...")
    MAX_RETRIES = 5
    RETRY_DELAYS = [3, 5, 8, 12, 15]  # seconds between retries (exponential-ish)

    token = None
    for attempt in range(MAX_RETRIES):
        token = extract_token()

        if token:
            # Check if token is expired
            expired, hours_remaining = is_token_expired(token)

            if expired:
                if attempt == 0:
                    print(f"Token extracted but EXPIRED ({hours_remaining:.1f} hours remaining)")
                    log_event("token_expired", f"Extracted token expired ({hours_remaining:.1f}h)")

                    # Force refresh on first attempt if expired
                    force_token_refresh()
                    print("Retrying with fresh credentials...")
                    continue
                else:
                    print(f"Token still expired after refresh attempt ({hours_remaining:.1f} hours)")
                    log_event("token_still_expired", f"Token still expired after refresh ({hours_remaining:.1f}h)")
                    token = None
            else:
                if attempt > 0:
                    print(f"Token found on attempt {attempt + 1}/{MAX_RETRIES}")
                    log_event("token_retry_success", f"Token extracted on retry attempt {attempt + 1}")
                print(f"Token is valid ({hours_remaining:.1f} hours remaining)")
                break

        # If this was the last attempt, don't wait
        if attempt < MAX_RETRIES - 1:
            wait_time = RETRY_DELAYS[attempt]
            print(f"Token not found (attempt {attempt + 1}/{MAX_RETRIES}), waiting {wait_time}s before retry...")
            log_event("token_retry", f"Token not found on attempt {attempt + 1}, retrying in {wait_time}s")
            time.sleep(wait_time)
            print("Retrying...")
        else:
            print(f"Token not found after {MAX_RETRIES} attempts")
            log_event("token_retry_failed", f"Token not found after {MAX_RETRIES} attempts")

    if token:
        print(f"Token extracted successfully ({len(token)} chars)")
        log_event("token_extracted", f"Token extracted successfully ({len(token)} chars)")

        # Update stack.env
        update_stack_env(token)
        log_event("token_updated", "stack.env updated with new token")

        # Restart container
        restart_container()
        log_event("container_restarted", "ITV container restarted")

        # Close Chrome
        cleanup()

        print()
        print("=" * 60)
        print("SUCCESS! Token updated and container restarted")
        print("=" * 60)
        print()

        log_event("script_success", "Token extraction completed successfully")

        # Show token info
        try:
            import base64
            parts = token.split('.')
            if len(parts) >= 2:
                payload = parts[1]
                padding = 4 - len(payload) % 4
                if padding != 4:
                    payload += '=' * padding
                decoded = base64.urlsafe_b64decode(payload)
                data = json.loads(decoded)

                if 'exp' in data:
                    exp_date = datetime.fromtimestamp(data['exp'], tz=timezone.utc)
                    hours_left = (exp_date - datetime.now(timezone.utc)).total_seconds() / 3600
                    print(f"Token expires: {exp_date}")
                    print(f"Hours remaining: {hours_left:.1f}")
                    log_event("token_info", f"Token expires: {exp_date}, Hours remaining: {hours_left:.1f}")
        except:
            pass

    else:
        print()
        print("=" * 60)
        print("ERROR: Could not extract token")
        print("=" * 60)
        print()
        print("Troubleshooting:")
        print("1. Make sure you're logged into ITVX in Chrome")
        print("2. Check that Chrome is running: ps aux | grep chromium")
        print("3. Check debug port: curl http://localhost:9222/json")
        log_event("token_failed", "Failed to extract token from Chrome")

if __name__ == '__main__':
    main()
