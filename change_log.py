"""
Simple change tracking for ITV tokens and stream URLs.
Logs to file so we can analyze actual expiration patterns.
"""

import os
import base64
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

LOG_FILE = os.path.join(os.path.dirname(__file__), 'change_log.json')
STATE_FILE = os.path.join(os.path.dirname(__file__), 'url_state.json')


def extract_base_url(url):
    """Extract base URL without JWT token."""
    try:
        if '/jwt/' in url:
            # Split at /jwt/ and take everything before it
            base = url.split('/jwt/')[0]
            return base + '/jwt/'
        return url
    except:
        return url


def extract_jwt_expiration(url):
    """Extract JWT expiration timestamp from URL."""
    try:
        if '/jwt/' in url:
            jwt_part = url.split('/jwt/')[1].split('?')[0].split('#')[0]
            parts = jwt_part.split('.')
            if len(parts) >= 2:
                payload = parts[1]
                padding = 4 - len(payload) % 4
                if padding != 4:
                    payload += '=' * padding
                decoded = base64.urlsafe_b64decode(payload)
                data = json.loads(decoded)
                if 'exp' in data:
                    return data['exp']
        return None
    except:
        return None


def extract_cdn(url):
    """Extract CDN provider from URL."""
    try:
        parsed = urlparse(url)
        if 'akamai' in parsed.netloc:
            return 'akamai'
        elif 'fastly' in parsed.netloc:
            return 'fastly'
        return 'unknown'
    except:
        return 'unknown'


def load_url_state():
    """Load previous URL state for comparison."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_url_state(state):
    """Save URL state for future comparisons."""
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def log_change(event_type, channel, details=None):
    """
    Log a change event.

    event_type: 'token_refresh', 'url_refresh', 'url_error', 'token_error'
    channel: Channel name or 'ALL' for token events
    details: Optional dict with extra info (old_value, new_value, error, etc.)
    """
    entry = {
        'timestamp': datetime.utcnow().isoformat(),
        'event_type': event_type,
        'channel': channel,
    }

    # Enhanced logging for URL refreshes
    if event_type == 'url_refresh' and details and 'url' in details:
        url = details['url']
        base_url = extract_base_url(url)
        jwt_exp = extract_jwt_expiration(url)
        cdn = extract_cdn(url)

        # Load previous state to detect changes
        state = load_url_state()
        channel_key = f"channel_{channel}"

        enhanced_details = {
            'url': url,
            'base_url': base_url,
            'jwt_expiration': jwt_exp,
            'cdn': cdn,
        }

        # Compare with previous URL
        if channel_key in state:
            prev = state[channel_key]
            prev_base = extract_base_url(prev.get('url', ''))
            prev_cdn = extract_cdn(prev.get('url', ''))
            prev_jwt = prev.get('jwt_expiration')

            # Detect what changed
            changes = []
            if base_url != prev_base:
                changes.append('base_url_changed')
            if cdn != prev_cdn:
                changes.append(f'cdn_switched_{prev_cdn}_to_{cdn}')
            if jwt_exp and prev_jwt and jwt_exp != prev_jwt:
                if jwt_exp > prev_jwt:
                    changes.append('jwt_renewed')
                else:
                    changes.append('jwt_older')

            if changes:
                enhanced_details['changes_detected'] = changes
            else:
                enhanced_details['changes_detected'] = ['url_identical']

            # Add comparison data
            enhanced_details['previous'] = {
                'base_url': prev_base,
                'cdn': prev_cdn,
                'jwt_expiration': prev_jwt
            }

        entry['details'] = enhanced_details

        # Update state
        state[channel_key] = {
            'url': url,
            'base_url': base_url,
            'jwt_expiration': jwt_exp,
            'cdn': cdn,
            'last_seen': entry['timestamp']
        }
        save_url_state(state)
    elif details:
        entry['details'] = details

    # Read existing log
    logs = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r') as f:
                logs = json.load(f)
        except (json.JSONDecodeError, IOError):
            logs = []

    # Add new entry (keep last 1000 entries)
    logs.append(entry)
    if len(logs) > 1000:
        logs = logs[-1000:]

    # Write back
    with open(LOG_FILE, 'w') as f:
        json.dump(logs, f, indent=2)


def get_logs(limit=100):
    """Get recent log entries."""
    if not os.path.exists(LOG_FILE):
        return []

    try:
        with open(LOG_FILE, 'r') as f:
            logs = json.load(f)
        return logs[-limit:]
    except (json.JSONDecodeError, IOError):
        return []


def get_token_history():
    """Analyze token refresh events to find patterns."""
    logs = get_logs(1000)
    token_events = [l for l in logs if l['event_type'] == 'token_refresh']

    if not token_events:
        return None

    # Calculate time between token refreshes
    intervals = []
    for i in range(1, len(token_events)):
        prev = datetime.fromisoformat(token_events[i-1]['timestamp'])
        curr = datetime.fromisoformat(token_events[i]['timestamp'])
        hours = (curr - prev).total_seconds() / 3600
        intervals.append(hours)

    if not intervals:
        return None

    return {
        'total_refreshes': len(token_events),
        'avg_hours_between': sum(intervals) / len(intervals) if intervals else 0,
        'min_hours': min(intervals) if intervals else 0,
        'max_hours': max(intervals) if intervals else 0,
        'last_refresh': token_events[-1]['timestamp'] if token_events else None,
    }


def get_url_history(channel=None):
    """Get URL refresh history for a channel."""
    logs = get_logs(1000)
    url_events = [l for l in logs if l['event_type'] == 'url_refresh']

    if channel:
        url_events = [l for l in url_events if l['channel'] == channel]

    return url_events[-20:]  # Last 20 events


def analyze_url_changes():
    """
    Analyze URL changes to determine if URLs change independently of tokens.

    Returns a summary of what actually changes between URL refreshes.
    """
    logs = get_logs(1000)
    url_events = [l for l in logs if l['event_type'] == 'url_refresh']

    if not url_events:
        return {
            'total_events': 0,
            'message': 'No URL refresh events logged yet. Check back tomorrow.'
        }

    analysis = {
        'total_events': len(url_events),
        'by_channel': {},
        'summary': {
            'base_url_changes': 0,
            'cdn_switches': 0,
            'jwt_renewals': 0,
            'identical_urls': 0
        },
        'conclusions': []
    }

    for event in url_events:
        channel = event['channel']
        details = event.get('details', {})

        if channel not in analysis['by_channel']:
            analysis['by_channel'][channel] = {
                'events': 0,
                'base_url_changes': 0,
                'cdn_switches': 0,
                'jwt_renewals': 0,
                'identical': 0
            }

        analysis['by_channel'][channel]['events'] += 1

        changes = details.get('changes_detected', [])
        if 'base_url_changed' in changes:
            analysis['by_channel'][channel]['base_url_changes'] += 1
            analysis['summary']['base_url_changes'] += 1
        if any('cdn_switched' in c for c in changes):
            analysis['by_channel'][channel]['cdn_switches'] += 1
            analysis['summary']['cdn_switches'] += 1
        if 'jwt_renewed' in changes:
            analysis['by_channel'][channel]['jwt_renewals'] += 1
            analysis['summary']['jwt_renewals'] += 1
        if 'url_identical' in changes:
            analysis['by_channel'][channel]['identical'] += 1
            analysis['summary']['identical_urls'] += 1

    # Generate conclusions
    total = analysis['total_events']
    if total > 0:
        base_pct = (analysis['summary']['base_url_changes'] / total) * 100
        cdn_pct = (analysis['summary']['cdn_switches'] / total) * 100
        jwt_pct = (analysis['summary']['jwt_renewals'] / total) * 100

        if base_pct > 50:
            analysis['conclusions'].append(f'Base URL changes in {base_pct:.0f}% of refreshes - URLs change independently')
        else:
            analysis['conclusions'].append(f'Base URL stable in {100-base_pct:.0f}% of refreshes')

        if cdn_pct > 20:
            analysis['conclusions'].append(f'CDN switches happen frequently ({cdn_pct:.0f}%) - likely load balancing')

        if jwt_pct > 80:
            analysis['conclusions'].append(f'JWT renews in {jwt_pct:.0f}% of refreshes - expected behavior')

    return analysis
