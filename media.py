"""Detect GIFs and pictures in a message. Pure logic, no Discord objects.

`attachments` everywhere is a list of (filename, content_type) tuples.
"""

from __future__ import annotations

import re

import config

# GIF picker links (tenor / giphy) and direct .gif links.
GIF_URL = re.compile(
    r"https?://(?:\S*?\.gif(?![A-Za-z0-9])|(?:[\w-]+\.)*(?:tenor|giphy)\.com)\S*", re.IGNORECASE
)
# Direct links to still pictures.
IMAGE_URL = re.compile(
    r"https?://\S*?\.(?:png|jpe?g|webp|bmp|heic|avif)(?![A-Za-z0-9])\S*", re.IGNORECASE
)
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".heic", ".avif")


def is_gif_file(name: str, content_type: str | None) -> bool:
    return name.lower().endswith(".gif") or (content_type or "").lower() == "image/gif"


def is_picture_file(name: str, content_type: str | None) -> bool:
    if is_gif_file(name, content_type):
        return False
    return (content_type or "").lower().startswith("image/") or name.lower().endswith(IMAGE_EXTENSIONS)


def has_gif(content: str, attachments: list[tuple[str, str | None]]) -> bool:
    return bool(GIF_URL.search(content)) or any(is_gif_file(n, t) for n, t in attachments)


def has_picture(content: str, attachments: list[tuple[str, str | None]]) -> bool:
    return bool(IMAGE_URL.search(GIF_URL.sub("", content))) or any(is_picture_file(n, t) for n, t in attachments)


def required_level(content: str, attachments: list[tuple[str, str | None]]) -> tuple[int, str] | None:
    """(level needed, what to call it) for the message, or None if it has no gated media.
    Pictures need the higher level, so a message with both uses that one."""
    if has_picture(content, attachments):
        return config.IMAGE_MIN_LEVEL, "pictures"
    if has_gif(content, attachments):
        return config.GIF_MIN_LEVEL, "GIFs"
    return None
