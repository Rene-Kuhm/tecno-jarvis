from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path


REPO_RELEASES_API = "https://api.github.com/repos/Rene-Kuhm/tecno-jarvis/releases/latest"
REPO_RELEASES_URL = "https://github.com/Rene-Kuhm/tecno-jarvis/releases/latest"
BASE_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = BASE_DIR / "VERSION"


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    update_available: bool
    release_url: str
    release_name: str


def current_version() -> str:
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", value)
    return tuple(int(part) for part in parts[:4]) or (0,)


def is_newer(latest: str, current: str) -> bool:
    latest_tuple = _version_tuple(latest)
    current_tuple = _version_tuple(current)
    max_len = max(len(latest_tuple), len(current_tuple))
    latest_tuple += (0,) * (max_len - len(latest_tuple))
    current_tuple += (0,) * (max_len - len(current_tuple))
    return latest_tuple > current_tuple


def check_latest_release(timeout: int = 8) -> UpdateInfo:
    current = current_version()
    request = urllib.request.Request(
        REPO_RELEASES_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "Tecno--J.A.R.V.I.S updater",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))

    latest = str(payload.get("tag_name") or "0.0.0").lstrip("v")
    release_url = str(payload.get("html_url") or REPO_RELEASES_URL)
    release_name = str(payload.get("name") or f"v{latest}")
    return UpdateInfo(
        current_version=current,
        latest_version=latest,
        update_available=is_newer(latest, current),
        release_url=release_url,
        release_name=release_name,
    )
