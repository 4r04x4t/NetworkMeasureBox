"""One matcher for secrets and personal data, used by every export, copy and report (2026-11-10).

Before this, four places had their own, different lists (config drive copy, crash reports, the diagnostic
bundle for AI assistants, the secrets keeper) and each missed keys the others had. Everything that leaves the
box or lands on the FAT boot partition, a USB stick, a report, a log or a chat goes through these functions.
"""
import re
from typing import Iterable

# Keys whose values are secrets: never shown, copied or sent anywhere.
SECRET_KEY_RE = re.compile(
    r"(password|passwd|passphrase|psk|token|auth_?key|api_?key|secret|private_?key|preshared_?key|credential)",
    re.I)
# Keys whose values identify a person, an account or a place: masked in anything shared (bundles, reports,
# crash reports, the boot-partition copy keeps them only when the owner asks for it).
PERSONAL_KEY_RE = re.compile(
    r"(^|_)(user|username|login|account_id|circuit_id|case_id|customer|from_addr|to_addrs|email|"
    r"allowed_chat_ids|chat_id|chat_ids|domain|fqdn|public_endpoint|endpoint|host_name|hostname)$",
    re.I)
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<cred>[^/@\s:]+(:[^/@\s]*)?)@", re.I)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

MASK = "<redacted>"


def is_secret_key(key: str) -> bool:
    return bool(SECRET_KEY_RE.search(key or ""))


def is_personal_key(key: str) -> bool:
    return bool(PERSONAL_KEY_RE.search((key or "").strip()))


def mask_value(value: str) -> str:
    value = str(value or "").strip()
    return f"<redacted, {len(value)} chars>" if value else ""


def scrub_text(text: str, personal: bool = True) -> str:
    """Free text (logs, messages, URLs): removes credentials in URLs (secrets, always) and, unless personal
    data may stay, e-mail addresses."""
    text = _URL_CREDENTIALS.sub(lambda m: m.group("scheme") + MASK + "@", text or "")
    return _EMAIL.sub(MASK, text) if personal else text


def redact_config_text(text: str, personal: bool = True, keep_keys: Iterable[str] = ()) -> str:
    """An ini-style text (nmb.conf) with secret values (and, by default, personal values) masked.

    Continuation lines of a multi-line value belong to the key above them and are masked with it.
    """
    keep = {k.lower() for k in keep_keys}
    out = []
    masking = False
    for line in (text or "").splitlines():
        stripped = line.strip()
        if masking and line[:1] in (" ", "\t") and stripped:
            continue                                   # continuation of a masked value: dropped
        masking = False
        if not stripped or stripped.startswith(("#", ";", "[")):
            out.append(line)
            continue
        key, sep, val = line.partition("=")
        if not sep:
            key, sep, val = line.partition(":")
        k = key.strip()
        if sep and k.lower() not in keep and val.strip() and (is_secret_key(k) or (personal and is_personal_key(k))):
            out.append(f"{key.rstrip()} = {mask_value(val)}")
            masking = True
        else:
            out.append(scrub_text(line, personal=personal) if sep else line)
    return "\n".join(out) + ("\n" if (text or "").endswith("\n") else "")
