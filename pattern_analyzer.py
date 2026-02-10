"""
Analyze event logs to find patterns and provide recommendations.

This module reads from patterns.json and generates insights about:
- Token lifetime patterns
- Failure patterns by time and type
- Correlation between token age and URL fetch failures
- Automated recommendations for cron optimization
"""

import json
import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict

LOG_FILE = os.path.join(os.path.dirname(__file__), 'patterns.json')


def load_events(hours_ago=168):  # Default: 7 days of data
    """
    Load events from the log file.

    Args:
        hours_ago: Only load events from the last N hours

    Returns:
        List of event dicts
    """
    if not os.path.exists(LOG_FILE):
        return []

    try:
        with open(LOG_FILE, 'r') as f:
            all_events = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return [e for e in all_events
            if datetime.fromisoformat(e['timestamp']) > cutoff]


def analyze_token_lifetime():
    """
    Analyze how long tokens actually last before failing.

    Returns:
        Dict with lifetime statistics or None if not enough data
    """
    events = load_events(hours_ago=168)

    # Find token refresh success events
    refreshes = [e for e in events if e['event_type'] == 'token_refresh_success']

    if len(refreshes) < 2:
        return None

    # Calculate intervals between refreshes
    intervals = []
    for i in range(1, len(refreshes)):
        try:
            prev_time = datetime.fromisoformat(refreshes[i-1]['timestamp'])
            curr_time = datetime.fromisoformat(refreshes[i]['timestamp'])
            hours = (curr_time - prev_time).total_seconds() / 3600
            intervals.append(hours)
        except (ValueError, KeyError):
            continue

    if not intervals:
        return None

    # Also check when 401 errors started occurring after each refresh
    # This tells us the actual useful lifetime of the token
    useful_lifetimes = []
    for refresh in refreshes:
        refresh_time = datetime.fromisoformat(refresh['timestamp'])

        # Find next 401 error after this refresh
        for e in events:
            if e['timestamp'] > refresh['timestamp'] and e['event_type'] in ['url_fetch_error_401', 'http_error_401']:
                try:
                    error_time = datetime.fromisoformat(e['timestamp'])
                    hours = (error_time - refresh_time).total_seconds() / 3600
                    if 0 < hours < 48:  # Sanity check
                        useful_lifetimes.append(hours)
                    break
                except (ValueError, KeyError):
                    continue

    result = {
        'avg_lifetime_hours': sum(intervals) / len(intervals),
        'min_lifetime_hours': min(intervals),
        'max_lifetime_hours': max(intervals),
        'sample_count': len(intervals),
        'last_refresh': refreshes[-1]['timestamp'] if refreshes else None,
    }

    # Add useful lifetime data if available
    if useful_lifetimes:
        result['avg_useful_lifetime_hours'] = sum(useful_lifetimes) / len(useful_lifetimes)
        result['min_useful_lifetime_hours'] = min(useful_lifetimes)
        result['useful_samples'] = len(useful_lifetimes)
        # Recommend refreshing at 75% of minimum useful lifetime
        result['recommended_refresh_interval_hours'] = max(1, int(min(useful_lifetimes) * 0.75))
    else:
        # Fallback to 75% of minimum interval
        result['recommended_refresh_interval_hours'] = max(1, int(min(intervals) * 0.75))

    return result


def analyze_failure_patterns():
    """
    Find patterns in failures.

    Returns:
        Dict with failure pattern analysis
    """
    events = load_events(hours_ago=168)

    errors_by_type = defaultdict(list)
    errors_by_hour = defaultdict(int)
    errors_by_channel = defaultdict(int)

    for e in events:
        if 'error' in e['event_type'] or e.get('severity') in ['error', 'critical']:
            errors_by_type[e['event_type']].append(e)

            # Group by hour of day
            try:
                dt = datetime.fromisoformat(e['timestamp'])
                hour_key = dt.hour
                errors_by_hour[hour_key] += 1
            except (ValueError, KeyError):
                continue

            # Group by channel if available
            channel = e.get('details', {}).get('channel')
            if channel:
                errors_by_channel[channel] += 1

    # Find error clusters (times with high error rates)
    peak_error_hours = sorted(errors_by_hour.items(), key=lambda x: x[1], reverse=True)[:5]

    # Calculate recent error rate (last 24 hours vs previous 24 hours)
    now = datetime.now(timezone.utc)
    yesterday_24 = now - timedelta(hours=48)
    recent_24_events = [e for e in events
                        if datetime.fromisoformat(e['timestamp']) > now - timedelta(hours=24)]
    previous_24_events = [e for e in events
                          if now - timedelta(hours=48) < datetime.fromisoformat(e['timestamp']) < now - timedelta(hours=24)]

    recent_errors = sum(1 for e in recent_24_events if 'error' in e['event_type'] or e.get('severity') in ['error', 'critical'])
    previous_errors = sum(1 for e in previous_24_events if 'error' in e['event_type'] or e.get('severity') in ['error', 'critical'])

    return {
        'error_counts': {k: len(v) for k, v in errors_by_type.items()},
        'peak_error_hours': [{'hour': h, 'count': c} for h, c in peak_error_hours],
        'errors_by_channel': dict(errors_by_channel),
        'total_errors': sum(len(v) for v in errors_by_type.values()),
        'recent_24h_errors': recent_errors,
        'previous_24h_errors': previous_errors,
        'error_trend': 'increasing' if recent_errors > previous_errors * 1.5 else 'stable' if abs(recent_errors - previous_errors) <= 2 else 'decreasing'
    }


def analyze_token_age_correlation():
    """
    Correlate token age with URL fetch failures.

    Returns:
        Dict showing how failures correlate with token age
    """
    events = load_events(hours_ago=168)

    # Get token refresh events to calculate age
    refresh_events = [e for e in events if e['event_type'] == 'token_refresh_success']

    if not refresh_events:
        return None

    # Find the most recent token refresh before each error
    failures_by_age = defaultdict(list)

    for e in events:
        if e['event_type'] in ['url_fetch_error_401', 'url_fetch_error_403', 'http_error_401']:
            error_time = datetime.fromisoformat(e['timestamp'])

            # Find the most recent token refresh before this error
            most_recent_refresh = None
            for refresh in refresh_events:
                refresh_time = datetime.fromisoformat(refresh['timestamp'])
                if refresh_time < error_time:
                    if most_recent_refresh is None or refresh_time > most_recent_refresh:
                        most_recent_refresh = refresh_time

            if most_recent_refresh:
                age_hours = (error_time - most_recent_refresh).total_seconds() / 3600
                age_bucket = int(age_hours / 6) * 6  # Bucket by 6-hour intervals
                failures_by_age[age_bucket].append(e['event_type'])

    if not failures_by_age:
        return None

    # Format results
    return {
        'failures_by_age_bucket': {
            f'{age}-{age+6}h': len(failures)
            for age, failures in sorted(failures_by_age.items())
        },
        'peak_failure_age_hours': max(failures_by_age.items(), key=lambda x: len(x[1]))[0] if failures_by_age else None,
        'total_failures_analyzed': sum(len(f) for f in failures_by_age.values())
    }


def generate_recommendations():
    """
    Generate actionable recommendations based on patterns.

    Returns:
        Dict with analysis and recommendations
    """
    token_analysis = analyze_token_lifetime()
    failure_analysis = analyze_failure_patterns()
    correlation_analysis = analyze_token_age_correlation()

    recommendations = []

    # Token lifetime recommendations
    if token_analysis:
        current_cron_hours = 12  # Current: twice daily = every 12 hours
        recommended_hours = token_analysis['recommended_refresh_interval_hours']

        # Check if we're refreshing too late
        avg_lifetime = token_analysis.get('avg_useful_lifetime_hours', token_analysis['avg_lifetime_hours'])
        if recommended_hours < current_cron_hours:
            recommendations.append({
                'priority': 'high',
                'category': 'token_refresh',
                'issue': f'Tokens expire after ~{avg_lifetime:.1f} hours on average',
                'recommendation': f'Increase cron frequency to every {recommended_hours} hours',
                'suggested_cron': f'0 */{recommended_hours} * * *',
                'current_cron': '0 7,20 * * * (every 12 hours)'
            })
        elif recommended_hours > current_cron_hours + 2:
            recommendations.append({
                'priority': 'low',
                'category': 'token_refresh',
                'issue': f'Tokens last ~{avg_lifetime:.1f} hours but we refresh every {current_cron_hours} hours',
                'recommendation': f'Current refresh frequency is adequate. Consider reducing to every {recommended_hours} hours to save resources.',
                'suggested_cron': f'0 */{recommended_hours} * * *'
            })

    # Failure pattern recommendations
    if failure_analysis['total_errors'] > 0:
        error_401_count = failure_analysis['error_counts'].get('url_fetch_error_401', 0) + \
                          failure_analysis['error_counts'].get('http_error_401', 0)

        if error_401_count > failure_analysis['total_errors'] * 0.3:
            recommendations.append({
                'priority': 'critical',
                'category': 'token_validity',
                'issue': f'{error_401_count} 401 errors (expired token) out of {failure_analysis["total_errors"]} total errors',
                'recommendation': 'Token refresh automation is failing or not running frequently enough.',
                'action': 'Manual token refresh required. Check chrome_password_login.py logs.'
            })

        # Check for recent error spike
        if failure_analysis['error_trend'] == 'increasing' and failure_analysis['recent_24h_errors'] > 5:
            recommendations.append({
                'priority': 'high',
                'category': 'error_spike',
                'issue': f'Error rate increased: {failure_analysis["previous_24h_errors"]} -> {failure_analysis["recent_24h_errors"]} errors (24h)',
                'recommendation': 'Check service logs for recent issues. May indicate ITV API changes or network problems.'
            })

    # Correlation analysis recommendations
    if correlation_analysis and correlation_analysis.get('peak_failure_age_hours'):
        peak_age = correlation_analysis['peak_failure_age_hours']
        if peak_age > 18:  # Failures mostly happen after 18 hours
            recommendations.append({
                'priority': 'medium',
                'category': 'token_age_correlation',
                'issue': f'Most failures occur when token is {peak_age}+ hours old',
                'recommendation': f'Set token refresh to run every {max(6, peak_age - 6)} hours to prevent failures.',
            })

    # No issues found
    if not recommendations:
        recommendations.append({
            'priority': 'info',
            'category': 'system_health',
            'issue': 'No significant issues detected',
            'recommendation': 'System is running smoothly. Continue monitoring.',
        })

    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'data_period_hours': 168,
        'token_analysis': token_analysis,
        'failure_analysis': failure_analysis,
        'correlation_analysis': correlation_analysis,
        'recommendations': recommendations
    }


def get_summary_dashboard():
    """
    Get a quick summary for the dashboard.

    Returns:
        Dict with summary stats
    """
    events = load_events(hours_ago=24)

    summary = {
        'total_events_24h': len(events),
        'errors_24h': 0,
        'token_refreshes_24h': 0,
        'url_fetches_24h': 0,
        'last_token_refresh': None,
        'last_error': None,
    }

    for e in events:
        if e.get('severity') in ['error', 'critical']:
            summary['errors_24h'] += 1
            if not summary['last_error']:
                summary['last_error'] = e['timestamp']

        if e['event_type'] == 'token_refresh_success':
            summary['token_refreshes_24h'] += 1
            summary['last_token_refresh'] = e['timestamp']

        if e['event_type'] in ['url_fetch_success', 'url_fetch_error_401', 'url_fetch_error_403',
                                'url_fetch_error_502', 'url_fetch_error_503']:
            summary['url_fetches_24h'] += 1

    return summary
