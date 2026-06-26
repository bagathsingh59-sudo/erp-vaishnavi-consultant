"""Helpers for building short, tidy download filenames.

Report downloads used to embed the full establishment company name (up to
50–60 characters), producing very long file names. `short_est_code` collapses
the company name to its initials (e.g. "SRI VENKATESHWARA ENTERPRISES" → "SVE")
so filenames stay short while still identifying the establishment.
"""
import re

# Common company-suffix / filler words that add no identifying value in a
# short code. Kept out of the initials so the code reflects the real name.
_NOISE_WORDS = {
    'AND', 'THE', 'OF', 'A', 'CO', 'COMPANY', 'PVT', 'PRIVATE', 'LTD',
    'LIMITED', 'LLP', 'INC', 'CORP', 'INDIA',
}


def short_est_code(name, max_len=10):
    """Return a short upper-case code for an establishment name.

    Strategy:
      • Multi-word names  → initials of the significant words ("SVE").
      • Single-word names → the word itself, truncated to ``max_len``.
    Falls back to "EST" when the name is empty. The result is always safe for
    use in a filename (letters/digits only).
    """
    if not name:
        return 'EST'
    words = re.findall(r'[A-Za-z0-9]+', name.upper())
    if not words:
        return 'EST'
    significant = [w for w in words if w not in _NOISE_WORDS] or words
    if len(significant) >= 2:
        code = ''.join(w[0] for w in significant)
    else:
        code = significant[0]
    code = code[:max_len]
    return code or 'EST'
