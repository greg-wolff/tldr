"""Decode newsletter click-tracker URLs offline.

No network calls: every decoder here is pure arithmetic on the URL itself, so a
refresh never depends on a tracker still being alive.  Anything that cannot be
decoded keeps its raw URL and is reported as unresolvable, which makes the app
render the headline without a link rather than linking somewhere misleading.
"""

import base64
import re
import urllib.parse as up
import zlib


def _b64url(s):
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))


def _flyover(url):
    """beehiiv: base64url -> zlib -> querystring, destination in `l=`."""
    tail = up.urlparse(url).path.rstrip('/').rsplit('/', 1)[-1]
    raw = zlib.decompress(_b64url(tail))
    qs = up.parse_qs(raw.decode('utf-8', 'replace'))
    dest = qs.get('l', [None])[0]
    return dest


def _verge(url):
    """link.theverge.com/click/<id>/<base64url of destination>/<hash>."""
    parts = [p for p in up.urlparse(url).path.split('/') if p]
    for p in parts:
        if len(p) < 16:
            continue
        try:
            cand = _b64url(p).decode('utf-8')
        except Exception:
            continue
        if cand.startswith(('http://', 'https://')):
            return cand
    return None


# host suffix -> decoder.  Order matters only in that the first match wins.
DECODERS = [
    ('link.mail.beehiiv.com', _flyover),
    ('link.theverge.com', _verge),
]

# Trackers with no offline decoding path at all.  SendGrid's encrypted click
# links (Keychain) run 1500-2500 characters and carry no recoverable payload.
OPAQUE = (
    'links.tldrnewsletter.com',
    '.ct.sendgrid.net',
    'url1234.keychain.com',
)


def unwrap(url):
    """Return the destination URL, or the input unchanged if it cannot decode."""
    if not url:
        return url
    host = (up.urlparse(url).hostname or '').lower()
    for suffix, fn in DECODERS:
        if host == suffix or host.endswith('.' + suffix):
            try:
                dest = fn(url)
            except Exception:
                dest = None
            if dest:
                return dest
            return url
    return url


def resolvable(url):
    if not url:
        return False
    host = (up.urlparse(url).hostname or '').lower()
    return not any(host == o.lstrip('.') or host.endswith(o) for o in OPAQUE)


if __name__ == '__main__':
    import sys
    for line in sys.stdin:
        line = line.strip()
        if line:
            print(unwrap(line))
