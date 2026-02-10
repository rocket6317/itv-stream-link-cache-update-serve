"""
Parse uvicorn access logs to detect HTTP error patterns.
Integrates with event_tracker to log errors as structured events.
"""

import re
import os
from pathlib import Path
from datetime import datetime, timedelta

LOG_FILE = Path("/app/logs/uvicorn.log")

# Pattern to match uvicorn access logs
# Example: 172.24.0.1:55882 - "GET /itvx?channel=ITV HTTP/1.1" 503 Service Unavailable
LOG_PATTERN = re.compile(
    r'(?P<ip>[\d.]+):\d+ - '
    r'"(?P<method>\w+) (?P<path>[^\s]+) (?P<protocol>[\w/.]+)" '
    r'(?P<status>\d+) (?P<message>.*)'
)


def parse_recent_logs(hours=1):
    """
    Parse logs from the last N hours for HTTP errors.

    Args:
        hours: Number of hours to look back

    Returns:
        List of error dicts with timestamp, status, method, path, message
    """
    if not LOG_FILE.exists():
        return []

    cutoff = datetime.now() - timedelta(hours=hours)
    errors = []

    try:
        with open(LOG_FILE, 'r') as f:
            for line in f:
                # Extract timestamp from log line
                # Format: 2026-02-10 12:34:56 - INFO ...
                try:
                    parts = line.split(' - ', 1)
                    if len(parts) < 2:
                        continue
                    timestamp_str = parts[0]
                    log_time = datetime.fromisoformat(timestamp_str)

                    if log_time < cutoff:
                        continue

                    # Match HTTP access pattern
                    match = LOG_PATTERN.search(line)
                    if match:
                        status = int(match.group('status'))
                        if status >= 400:  # Client and server errors
                            errors.append({
                                'timestamp': log_time.isoformat(),
                                'status': status,
                                'method': match.group('method'),
                                'path': match.group('path'),
                                'message': match.group('message').strip()
                            })
                except (ValueError, IndexError):
                    continue
    except (IOError, OSError):
        pass

    return errors


def scan_and_log_errors():
    """
    Scan recent logs and log errors to event tracker.

    Returns:
        Number of errors found and logged, or None if parsing failed
    """
    try:
        # Import here to avoid circular dependency
        from event_tracker import log_event
    except ImportError:
        return None

    errors = parse_recent_logs(hours=1)

    if not errors:
        return 0

    # Group by status code
    by_status = {}
    for e in errors:
        status = e['status']
        if status not in by_status:
            by_status[status] = []
        by_status[status].append(e)

    # Log aggregated error events
    for status, status_errors in by_status.items():
        event_type = {
            401: 'http_error_401',
            403: 'http_error_403',
            502: 'http_error_502',
            503: 'http_error_503',
            504: 'http_error_504',
        }.get(status, 'http_error_other')

        # Extract unique paths (avoid duplicates)
        unique_paths = list(set(e['path'] for e in status_errors))

        log_event(event_type, {
            'count': len(status_errors),
            'paths': unique_paths[:10],  # First 10 unique paths
            'sample_message': status_errors[0]['message']
        }, severity='error' if status >= 500 else 'warning')

    return len(errors)


def get_log_summary(hours=24):
    """
    Get a summary of HTTP errors from logs.

    Args:
        hours: Time window in hours

    Returns:
        Dict with error counts by status code
    """
    errors = parse_recent_logs(hours=hours)

    summary = {
        'total_errors': len(errors),
        'by_status': {},
        'by_path': {},
        'time_window_hours': hours
    }

    for e in errors:
        status = e['status']
        summary['by_status'][status] = summary['by_status'].get(status, 0) + 1

        path = e['path']
        summary['by_path'][path] = summary['by_path'].get(path, 0) + 1

    return summary
