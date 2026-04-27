"""
Polls the Flask face-recognition API and inserts new entries as Alert rows.

Triggers on `count` changes: each time the API's `count` value differs from the
previous poll, every new entry (deduped by image filename) becomes one Alert.

Severity rules:
    - status == 'authorized'  -> low    (recognized person)
    - status == 'no_face'     -> high   (no face -> treat as suspicious)
    - anything else           -> high   (unauthorized / unknown)

Run from the Django project root (the directory holding manage.py):

    python -m core.alert_poller

Environment variables:
    FACE_API_URL              full URL to the entries endpoint
                              (default: http://127.0.0.1:5000/entries)
    FACE_API_POLL_INTERVAL    seconds between polls (default: 5)
"""

import logging
import os
import sys
import time
from pathlib import Path


def _bootstrap_django() -> None:
    """Make the script runnable standalone (outside `manage.py shell`)."""
    base_dir = Path(__file__).resolve().parent.parent
    if str(base_dir) not in sys.path:
        sys.path.insert(0, str(base_dir))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dronesec.settings')
    import django
    django.setup()


if __name__ == '__main__':
    _bootstrap_django()

import requests

from core.models import Alert


API_URL = os.getenv('FACE_API_URL', 'http://127.0.0.1:5000/entries')
POLL_INTERVAL_SECONDS = int(os.getenv('FACE_API_POLL_INTERVAL', '5'))
HTTP_TIMEOUT_SECONDS = 10
MAX_TRACKED_KEYS = 5000

logger = logging.getLogger(__name__)


def _entry_key(entry: dict) -> str:
    """Stable dedup key for one API entry."""
    return entry.get('image') or entry.get('timestamp') or ''


def _build_alert_fields(entry: dict) -> dict:
    result = entry.get('result') or {}
    status = (result.get('status') or '').lower()
    name = result.get('name') or 'Unknown'
    distance = result.get('distance')
    timestamp = entry.get('timestamp', '')
    image = entry.get('image', '')

    if status == 'authorized':
        title = f'Authorized person detected: {name}'
        description = (
            f'Recognized "{name}" (distance={distance}) '
            f'at {timestamp}. Image: {image}.'
        )
        severity = 'low'
    elif status == 'no_face':
        title = 'Motion detected (no face)'
        description = (
            f'Motion captured but no face could be identified at {timestamp}. '
            f'Image: {image}.'
        )
        severity = 'high'
    else:
        title = 'Unauthorized person detected'
        description = (
            f'Unrecognized person (status={status or "unknown"}) at {timestamp}. '
            f'Image: {image}.'
        )
        severity = 'high'

    return {
        'title': title[:200],
        'description': description,
        'severity': severity,
        'alert_type': 'face',
    }


def fetch_api(url: str = API_URL) -> dict | None:
    try:
        response = requests.get(url, timeout=HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning('Failed to fetch %s: %s', url, exc)
        return None


def poll_once(state: dict) -> int:
    """
    One poll cycle. `state` keeps cross-call info:
        last_count: previous `count` value from the API
        seen_keys:  set of entry keys already turned into Alerts

    Returns the number of new Alerts inserted this cycle.
    """
    payload = fetch_api()
    if not payload:
        return 0

    count = payload.get('count', 0)
    entries = payload.get('entries') or []

    # First poll: snapshot current state so we don't backfill historical rows.
    if 'last_count' not in state:
        state['last_count'] = count
        state['seen_keys'] = {
            key for key in (_entry_key(e) for e in entries) if key
        }
        logger.info('Initial snapshot: count=%s, tracking %d existing entries',
                    count, len(state['seen_keys']))
        return 0

    if count == state['last_count']:
        return 0

    seen = state['seen_keys']
    inserted = 0
    for entry in entries:
        key = _entry_key(entry)
        if not key or key in seen:
            continue
        fields = _build_alert_fields(entry)
        Alert.objects.create(**fields)
        seen.add(key)
        inserted += 1

    state['last_count'] = count

    # Bound memory growth.
    if len(seen) > MAX_TRACKED_KEYS:
        # Drop oldest half — order is insertion order in CPython 3.7+.
        keep = list(seen)[-MAX_TRACKED_KEYS // 2:]
        state['seen_keys'] = set(keep)

    if inserted:
        logger.info('Inserted %d new alert(s) (count=%s)', inserted, count)
    return inserted


def run_forever(interval: int = POLL_INTERVAL_SECONDS) -> None:
    state: dict = {}
    logger.info('Polling %s every %ss', API_URL, interval)
    while True:
        try:
            poll_once(state)
        except Exception:
            logger.exception('Poller iteration failed')
        time.sleep(interval)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s [alert_poller] %(message)s',
    )
    run_forever()
