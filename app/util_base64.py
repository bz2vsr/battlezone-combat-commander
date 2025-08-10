from __future__ import annotations

import base64

_BASE64_STD = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_BASE64_ALT = "@123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"


def _alt_to_std(s: str) -> str:
    trans = {a: _BASE64_STD[i] for i, a in enumerate(_BASE64_ALT)}
    return "".join(trans.get(ch, ch) for ch in s)


def decode_raknet_guid(guid: str) -> bytes:
    # Convert alternate alphabet to standard and pad with '=' to multiple of 4
    std = _alt_to_std(guid)
    if len(std) % 4 != 0:
        std = std.ljust((len(std) + 3) & ~3, "=")
    return base64.b64decode(std)


def b64_to_str(s: str) -> str:
    try:
        return base64.b64decode(s + "==").decode("utf-8", errors="ignore").strip("\x00")
    except Exception:
        return s


