"""Domain normalization and validation shared by both Tomatto services.

A "domain" input may be a bare host (``example.com``), a full URL
(``https://user:pass@news.example.co.uk/path?x=1#f``), uppercase, carry a port
or a trailing dot. We normalize it to its lowercase ASCII (punycode) hostname
and reject anything that is not a syntactically valid multi-label host.
"""

from __future__ import annotations

import re

import idna

# Labels: alnum/unicode + hyphens, no leading/trailing hyphen, 1-63 chars each;
# total length <= 253. Underscores are intentionally NOT allowed (invalid in
# hostnames per IDNA) — the test suite uses that as a negative case.
_LABEL = r"[A-Za-z0-9¡-￿-]"
_HOSTNAME_RE = re.compile(
    rf"^(?=[^\n]{{1,253}}$)(?!-){_LABEL}{{1,63}}(?<!-)"
    rf"(\.(?!-){_LABEL}{{1,63}}(?<!-))*$"
)


def normalize_domain(raw: str) -> str:
    """Return the normalized lowercase ASCII hostname for ``raw``.

    Raises ``ValueError`` with a human-readable reason when the input is not a
    valid multi-label domain (FastAPI turns this into a 422 response).
    """
    if not isinstance(raw, str):
        raise ValueError("domain must be a string")

    s = raw.strip()
    if not s:
        raise ValueError("domain must not be empty")
    if any(ch.isspace() for ch in s):
        raise ValueError(f"{raw!r} contains whitespace")

    # Strip scheme, path/query/fragment and credentials.
    if "://" in s:
        s = s.split("://", 1)[1]
    s = re.split(r"[/?#]", s, maxsplit=1)[0]
    if "@" in s:
        s = s.rsplit("@", 1)[1]

    # Reject IPv6 literals; strip a numeric port.
    if s.startswith("["):
        raise ValueError("IPv6 address literals are not supported")
    if ":" in s:
        host, _, port = s.partition(":")
        if not port.isdigit():
            raise ValueError(f"{raw!r} has an invalid port")
        s = host

    s = s.rstrip(".").lower()
    if "." not in s:
        raise ValueError(f"{raw!r} is not a multi-label domain (single labels like 'localhost' are rejected)")
    if not _HOSTNAME_RE.match(s):
        raise ValueError(f"{raw!r} is not a valid domain")

    # Unicode domains -> punycode (ACE). Already-ASCII hosts pass through.
    try:
        s.encode("ascii")
        return s
    except UnicodeEncodeError:
        try:
            return idna.encode(s, uts46=True).decode("ascii").rstrip(".")
        except (idna.IDNAError, UnicodeError) as exc:
            raise ValueError(f"{raw!r} is not a valid internationalized domain: {exc}") from exc
