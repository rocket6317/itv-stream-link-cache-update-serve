#!/usr/bin/env python3
"""
ITV Token Refresher for Headless DietPi

This script automates the extraction of ITV access tokens using Selenium
with headless Chrome. It's designed to run on DietPi or any headless Linux system.

Requirements:
- chromium-chromedriver
- Python 3 with selenium
- Xvfb (virtual X server for headless operation)

Usage:
    python3 refresh_token.py

The script will:
1. Open headless Chrome
2. Navigate to ITVX
3. Wait for manual login (first time only)
4. Extract the JWT token
5. Update stack.env
"""

import os
import sys
import json
import time
import subprocess
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# Configuration
ENV_FILE = os.path.join(os.path.dirname(__file__), 'stack.env')
ITV_URL = "https://www.itv.com/watch"
HEADLESS = os.getenv('HEADLESS', 'true').lower() == 'true'
CHROME_PROFILE_DIR = os.path.join(os.path.dirname(__file__), '.chrome_profile')


def setup_chrome_options():
    """Configure Chrome for headless operation with persistent profile."""
    options = Options()

    # Create and set user data directory for persistent profile
    profile_dir = Path(CHROME_PROFILE_DIR)
    profile_dir.mkdir(exist_ok=True)
    options.add_argument(f'--user-data-dir={CHROME_PROFILE_DIR}')

    if HEADLESS:
        options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-software-rasterizer')
        options.add_argument('--window-size=1920,1080')

    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    options.add_experimental_option('useAutomationExtension', False)

    # Set user agent to look like a real browser
    options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

    return options


def extract_token_from_network(driver, timeout=120):
    """
    Extract JWT token by intercepting network requests.
    This waits for a request to simulcast.itv.com and extracts the token.
    """
    token = None
    start_time = time.time()

    print("Monitoring network requests for token...")

    while time.time() - start_time < timeout:
        try:
            # Execute JavaScript to get performance logs (network requests)
            logs = driver.get_log('performance')

            for entry in logs:
                try:
                    log = json.loads(entry['message'])
                    if log['message']['method'] == 'Network.requestWillBeSent':
                        url = log['message']['params']['request']['url']

                        # Look for simulcast.itv.com requests
                        if 'simulcast.itv.com' in url and '/playlist/itvonline/' in url:
                            # Try to get the request body
                            post_data = log['message']['params'].get('request', {}).get('postData')
                            if post_data:
                                try:
                                    data = json.loads(post_data)
                                    if 'user' in data and 'token' in data['user']:
                                        token = data['user']['token']
                                        print(f"✅ Found token via network monitoring!")
                                        return token
                                except json.JSONDecodeError:
                                    pass
                except (KeyError, json.JSONDecodeError):
                    pass

            time.sleep(1)

        except Exception as e:
            print(f"Error reading logs: {e}")
            time.sleep(2)

    return token


def extract_token_from_page(driver):
    """Try to extract token by parsing page JavaScript variables."""
    try:
        # Try to get token from page state
        token = driver.execute_script("""
            // Try to find token in various places
            if (window.__INITIAL_STATE__ &&
                window.__INITIAL_STATE__.auth &&
                window.__INITIAL_STATE__.auth.user &&
                window.__INITIAL_STATE__.auth.user.token) {
                return window.__INITIAL_STATE__.auth.user.token;
            }

            if (window.itvConfig &&
                window.itvConfig.user &&
                window.itvConfig.user.token) {
                return window.itvConfig.user.token;
            }

            return null;
        """)

        if token:
            print("✅ Found token in page state!")
            return token
    except Exception as e:
        print(f"Could not extract from page: {e}")

    return None


def login_and_extract_token():
    """
    Main function to navigate to ITVX and extract the JWT token.
    On first run, this will require manual login in the headless browser.
    """
    print("=" * 60)
    print("ITV Token Refresher")
    print("=" * 60)
    print()

    options = setup_chrome_options()

    # Enable performance logging to capture network requests
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

    # Find chromedriver
    service = None
    try:
        # Try common chromedriver locations
        driver_paths = [
            '/usr/bin/chromedriver',
            '/usr/local/bin/chromedriver',
            'chromedriver'
        ]

        for path in driver_paths:
            if os.path.exists(path):
                service = Service(path)
                break

        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        print(f"❌ Error starting Chrome: {e}")
        print()
        print("Please install chromium and chromedriver on your DietPi:")
        print("  sudo apt install chromium-chromedriver")
        print("  sudo apt install chromium")
        return None

    try:
        print(f"🌐 Navigating to ITVX...")
        driver.get(ITV_URL)

        # Check if already logged in
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='sign-in-button']"))
            )
            print()
            print("=" * 60)
            print("⚠️  NOT LOGGED IN")
            print("=" * 60)
            print()
            print("Please log in to ITVX in the browser window.")
            print("If running headless, temporarily disable headless mode:")
            print("  export HEADLESS=false")
            print("  python3 refresh_token.py")
            print()
            print("Waiting for login (max 5 minutes)...")
            print("=" * 60)
            print()

            # Wait for user to log in (check for sign-out button which means logged in)
            WebDriverWait(driver, 300).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "[data-testid='sign-out-button'], button[aria-label*='Sign out']"))
            )
            print("✅ Logged in successfully!")

        except TimeoutException:
            # Already logged in
            print("✅ Already logged in!")

        print("🔄 Extracting token...")

        # Navigate to a live channel to trigger simulcast request
        print("   Navigating to live channel...")
        driver.get("https://www.itv.com/watch?channel=itv")
        time.sleep(5)

        # Try to extract token
        token = extract_token_from_network(driver, timeout=30)

        if not token:
            print("   Trying alternative extraction method...")
            token = extract_token_from_page(driver)

        if token:
            return token
        else:
            print("❌ Failed to extract token")
            print()
            print("Troubleshooting:")
            print("  1. Make sure you're logged into ITVX")
            print("  2. Try disabling headless mode: HEADLESS=false python3 refresh_token.py")
            print("  3. Check if ITVX has changed their authentication")
            return None

    finally:
        driver.quit()


def update_env_file(token):
    """Update the stack.env file with the new token."""
    print()
    print("📝 Updating stack.env...")

    try:
        # Read current env file
        if os.path.exists(ENV_FILE):
            with open(ENV_FILE, 'r') as f:
                lines = f.readlines()
        else:
            lines = []

        # Update or add ITV_ACCESS_TOKEN
        updated = False
        for i, line in enumerate(lines):
            if line.startswith('ITV_ACCESS_TOKEN='):
                lines[i] = f'ITV_ACCESS_TOKEN={token}\n'
                updated = True
                break

        if not updated:
            lines.append(f'\nITV_ACCESS_TOKEN={token}\n')

        # Write back
        with open(ENV_FILE, 'w') as f:
            f.writelines(lines)

        print(f"✅ Updated {ENV_FILE}")
        return True

    except Exception as e:
        print(f"❌ Error updating env file: {e}")
        return False


def signal_app_to_reload():
    """Signal the running application to reload the token."""
    print()
    print("🔄 Signaling app to reload token...")

    # Create a flag file that the app can check
    flag_file = os.path.join(os.path.dirname(__file__), '.reload_token')
    try:
        with open(flag_file, 'w') as f:
            f.write(str(time.time()))
        print(f"✅ Created reload signal file")
    except Exception as e:
        print(f"⚠️  Could not create reload signal: {e}")


def restart_container():
    """Restart the Docker container to pick up new token."""
    import subprocess
    try:
        # Find and restart the ITV container
        result = subprocess.run(
            ['docker', 'ps', '--filter', 'name=itv', '--format', '{{.Names}}'],
            capture_output=True,
            text=True,
            timeout=10
        )
        container_name = result.stdout.strip()
        if container_name:
            subprocess.run(
                ['docker', 'restart', container_name],
                capture_output=True,
                timeout=30
            )
            print(f"✅ Restarted container: {container_name}")
        else:
            print("⚠️  Could not find ITV container to restart")
    except Exception as e:
        print(f"⚠️  Could not restart container: {e}")


def main():
    print()

    # Check for interactive mode
    if len(sys.argv) > 1 and sys.argv[1] == '--interactive':
        os.environ['HEADLESS'] = 'false'
        print("🖥️  Running in INTERACTIVE mode (with visible browser)")
        print()

    # Extract token
    token = login_and_extract_token()

    if not token:
        print()
        print("❌ Token extraction failed")
        sys.exit(1)

    # Verify token format
    if not token.startswith('eyJ'):
        print(f"❌ Invalid token format (should start with 'eyJ')")
        sys.exit(1)

    print()
    print(f"✅ Token extracted successfully ({len(token)} characters)")

    # Update env file
    if update_env_file(token):
        signal_app_to_reload()
        restart_container()

        print()
        print("=" * 60)
        print("✅ SUCCESS! Token updated")
        print("=" * 60)
        print()
        print(f"Next refresh needed: ~24 hours")
        print()

        # Decode and show expiration
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
                    from datetime import datetime
                    exp_date = datetime.fromtimestamp(data['exp'])
                    print(f"Token expires: {exp_date}")
        except Exception:
            pass

        sys.exit(0)


if __name__ == '__main__':
    main()
