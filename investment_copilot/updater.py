from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from .config import BASE_DIR, DATA_DIR

CONFIG_PATH = DATA_DIR / "update_config.json"
PENDING_PATH = DATA_DIR / "pending_update.json"
BACKUP_DIR = BASE_DIR / "backups"
VERSION_PATH = BASE_DIR / "VERSION.txt"
DEFAULT_MANIFEST_URL = "https://raw.githubusercontent.com/trytobetheone/investment-copilot-updates/main/update_manifest.json"


@dataclass
class UpdateInfo:
    current_version: str
    latest_version: str | None = None
    download_url: str | None = None
    sha256: str | None = None
    notes: list[str] | None = None
    available: bool = False
    error: str | None = None


def current_version() -> str:
    try:
        return VERSION_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return "0.0.0"


def _version_tuple(value: str) -> tuple[int, ...]:
    clean = value.strip().lower().lstrip("v")
    parts = []
    for p in clean.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


def normalize_manifest_url(value: str) -> str:
    """Accept either a manifest URL or a normal GitHub repository URL."""
    url = (value or "").strip()
    if not url:
        return ""

    if url.startswith("https://raw.githubusercontent.com/"):
        return url

    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path.strip("/")
        if host in {"github.com", "www.github.com"}:
            parts = path.split("/")
            if len(parts) >= 2:
                owner = parts[0]
                repo = parts[1]
                if repo.endswith(".git"):
                    repo = repo[:-4]

                # github.com/owner/repo/blob/branch/update_manifest.json
                if len(parts) >= 5 and parts[2] == "blob":
                    branch = parts[3]
                    file_path = "/".join(parts[4:])
                    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{file_path}"

                # github.com/owner/repo(.git)
                if len(parts) == 2:
                    return f"https://raw.githubusercontent.com/{owner}/{repo}/main/update_manifest.json"
    except Exception:
        pass

    return url


def load_update_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"manifest_url": DEFAULT_MANIFEST_URL}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        data["manifest_url"] = normalize_manifest_url(str(data.get("manifest_url") or ""))
        return data
    except Exception:
        return {"manifest_url": DEFAULT_MANIFEST_URL}


def save_update_config(manifest_url: str) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_manifest_url(manifest_url)
    CONFIG_PATH.write_text(
        json.dumps({"manifest_url": normalized}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def check_for_update(timeout: int = 12) -> UpdateInfo:
    cur = current_version()
    config = load_update_config()
    url = normalize_manifest_url(str(config.get("manifest_url") or ""))
    if not url:
        return UpdateInfo(current_version=cur, error="업데이트 채널이 아직 연결되지 않았습니다.")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "InvestmentCommitteeCopilot-Updater/1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8-sig")
            payload = json.loads(raw)
        latest = str(payload["version"]).strip()
        download_url = str(payload["download_url"]).strip()
        sha256 = str(payload.get("sha256") or "").strip().lower() or None
        notes = payload.get("notes") or []
        if not isinstance(notes, list):
            notes = [str(notes)]
        return UpdateInfo(
            current_version=cur,
            latest_version=latest,
            download_url=download_url,
            sha256=sha256,
            notes=[str(x) for x in notes],
            available=_version_tuple(latest) > _version_tuple(cur),
        )
    except json.JSONDecodeError:
        return UpdateInfo(
            current_version=cur,
            error="업데이트 채널이 JSON manifest가 아닙니다. GitHub 저장소 주소 또는 update_manifest.json 주소를 입력하세요.",
        )
    except Exception as exc:
        return UpdateInfo(current_version=cur, error=f"업데이트 확인 실패: {exc}")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def download_update(info: UpdateInfo, timeout: int = 90) -> Path:
    if not info.download_url or not info.latest_version:
        raise RuntimeError("다운로드 가능한 업데이트 정보가 없습니다.")
    target_dir = DATA_DIR / "updates"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"investment_copilot_{info.latest_version}.zip"
    temp = target.with_suffix(".part")
    req = urllib.request.Request(info.download_url, headers={"User-Agent": "InvestmentCommitteeCopilot-Updater/1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, temp.open("wb") as out:
        shutil.copyfileobj(resp, out)
    if info.sha256:
        actual = _sha256(temp)
        if actual != info.sha256:
            temp.unlink(missing_ok=True)
            raise RuntimeError("업데이트 파일 무결성(SHA-256) 검증에 실패했습니다.")
    temp.replace(target)
    return target


def stage_update(info: UpdateInfo, zip_path: Path) -> None:
    PENDING_PATH.write_text(
        json.dumps(
            {
                "version": info.latest_version,
                "zip_path": str(zip_path.resolve()),
                "sha256": info.sha256,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def launch_updater_and_exit() -> None:
    script = BASE_DIR / "scripts" / "apply_update.py"
    if not script.exists():
        raise RuntimeError("업데이트 적용 스크립트를 찾을 수 없습니다.")
    python = Path(sys.executable)
    pid = os.getpid()
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    subprocess.Popen([str(python), str(script), "--wait-pid", str(pid)], cwd=str(BASE_DIR), creationflags=flags)
    os._exit(0)
