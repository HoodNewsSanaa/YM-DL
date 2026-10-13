"""Present downloader diagnostics in the app's music terminology."""
import re


def music_message(message) -> str:
    return re.sub(r"\bvideos?\b", lambda match: "Tracks" if match.group(0)[0].isupper() and match.group(0).lower().endswith("s")
                  else "Track" if match.group(0)[0].isupper()
                  else "tracks" if match.group(0).endswith("s") else "track", str(message), flags=re.I)


def invalid_youtube_cookies(message) -> bool:
    """Recognize explicit cookie warnings, never infer invalid cookies from 403."""
    value = " ".join(str(message).lower().split())
    return bool(re.search(r"\bcookies?\s+(?:(?:are|is|were|was)\s+(?:no longer valid|invalid|expired|rotated)|"
                          r"(?:have|has)\s+(?:likely\s+)?(?:expired|been\s+rotated)|expired|rotated)\b", value))
