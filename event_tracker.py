"""
Centralized event tracking for ITV service.
Logs structured events to patterns.json for analysis.

This module provides a unified logging interface for all components:
- Token refresh events
- URL fetch events
- HTTP error events
- Automation script events
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = os.path.join(os.path.dirname(__file__), 'patterns.json')
MAX_ENTRIES = 5000  # Keep ~7 days of data

# Event type categories with descriptions
EVENT_TYPES = {
    # Token events
    'token_refresh_start': 'Token refresh script started',
    'token_refresh_success': 'Token successfully refreshed',
    'token_refresh_failed': 'Token refresh failed',
    'token_expired': 'Token was expired when checked',
    'token_skipped': 'Token refresh skipped (still valid)',

    # URL events (from client.py)
    'url_fetch_start': 'Started fetching stream URL',
    'url_fetch_success': 'Successfully fetched stream URL',
    'url_fetch_error_401': 'URL fetch failed with 401 (invalid token)',
    'url_fetch_error_403': 'URL fetch failed with 403 (forbidden)',
    'url_fetch_error_502': 'URL fetch failed with 502 (bad gateway)',
    'url_fetch_error_503': 'URL fetch failed with 503 (service unavailable)',
    'url_fetch_error_504': 'URL fetch failed with 504 (gateway timeout)',
    'url_fetch_error_timeout': 'URL fetch timed out',
    'url_fetch_error_other': 'URL fetch failed with other error',

    # HTTP events (from uvicorn access logs)
    'http_error_401': 'HTTP 401 errors detected in access logs',
    'http_error_403': 'HTTP 403 errors detected in access logs',
    'http_error_502': 'HTTP 502 errors detected in access logs',
    'http_error_503': 'HTTP 503 errors detected in access logs (service unavailable)',
    'http_error_504': 'HTTP 504 errors detected in access logs',
    'http_error_other': 'Other HTTP 4xx/5xx errors in access logs',

    # Automation events
    'automation_login_attempt': 'Login automation attempted',
    'automation_login_success': 'Login automation succeeded',
    'automation_login_failed': 'Login automation failed',
    'automation_cookie_consent': 'Cookie consent modal detected',
    'automation_passcode_flow': 'Passcode flow triggered',
    'automation_password_flow': 'Password flow triggered',
    'automation_retry': 'Automation retry triggered',
    'automation_chrome_start': 'Chrome browser started',
    'automation_chrome_failed': 'Chrome browser failed to start',

    # System events
    'container_restart': 'Docker container restarted',
    'startup': 'Service started up',
    'cache_exhausted': 'Cache entry expired',
    'cache_refresh_start': 'Cache refresh started',
    'cache_refresh_complete': 'Cache refresh completed',
}


def log_event(event_type, details=None, severity='info'):
    """
    Log a structured event.

    Args:
        event_type: One of EVENT_TYPES keys
        details: Dict with additional context (token_age_hours, error_message, etc.)
        severity: 'info', 'warning', 'error', 'critical'

    Returns:
        The logged entry dict, or None if logging failed
    """
    entry = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'event_type': event_type,
        'description': EVENT_TYPES.get(event_type, event_type),
        'severity': severity,
        'details': details or {}
    }

    try:
        # Read existing log
        logs = []
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, 'r') as f:
                    logs = json.load(f)
            except (json.JSONDecodeError, IOError):
                logs = []

        # Add new entry
        logs.append(entry)
        if len(logs) > MAX_ENTRIES:
            logs = logs[-MAX_ENTRIES:]

        # Write back
        with open(LOG_FILE, 'w') as f:
            json.dump(logs, f, indent=2)

        return entry
    except Exception as e:
        # Don't fail the application if logging fails
        print(f"[event_tracker] Failed to log event: {e}")
        return None


def get_events(event_type=None, limit=1000, hours_ago=None, severity=None):
    """
    Retrieve events with optional filtering.

    Args:
        event_type: Filter by specific event type
        limit: Maximum number of events to return
        hours_ago: Only return events from the last N hours
        severity: Filter by severity level (info, warning, error, critical)

    Returns:
        List of event dicts, most recent first
    """
    if not os.path.exists(LOG_FILE):
        return []

    try:
        with open(LOG_FILE, 'r') as f:
            logs = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

    # Filter by event type
    if event_type:
        logs = [e for e in logs if e['event_type'] == event_type]

    # Filter by severity
    if severity:
        logs = [e for e in logs if e.get('severity') == severity]

    # Filter by time
    if hours_ago:
        cutoff = datetime.now(timezone.utc).timestamp() - (hours_ago * 3600)
        logs = [e for e in logs if datetime.fromisoformat(e['timestamp']).timestamp() > cutoff]

    # Return most recent first, limited
    return logs[-limit:][::-1]


def get_event_stats(hours_ago=24):
    """
    Get statistics about events in the given time window.

    Args:
        hours_ago: Time window in hours

    Returns:
        Dict with event counts by type and severity
    """
    events = get_events(hours_ago=hours_ago, limit=10000)

    stats = {
        'total': len(events),
        'by_type': {},
        'by_severity': {'info': 0, 'warning': 0, 'error': 0, 'critical': 0},
        'time_window_hours': hours_ago
    }

    for e in events:
        # Count by type
        etype = e['event_type']
        stats['by_type'][etype] = stats['by_type'].get(etype, 0) + 1

        # Count by severity
        sev = e.get('severity', 'info')
        if sev in stats['by_severity']:
            stats['by_severity'][sev] += 1

    return stats


def get_recent_errors(limit=50, hours_ago=24):
    """
    Get recent error events for debugging.

    Args:
        limit: Maximum number of errors to return
        hours_ago: Time window in hours

    Returns:
        List of error events
    """
    return get_events(
        severity='error',
        hours_ago=hours_ago,
        limit=limit
    ) + get_events(
        severity='critical',
        hours_ago=hours_ago,
        limit=limit
    )
