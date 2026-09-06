from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PENDING = DATA / "pending_update.json"
BACKUPS = ROOT / "backups"
PRESERVE_NAMES = {"data", "backups", ".venv"}
PRESERVE_FILES = {".env"}


def wait_for_pid(pid: int, timeout: int = 45) -> None:
    if pid <= 0:
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5
            ).stdout
            if str(pid) not in out:
                return
        except Exception:
            time.sleep(1)
            continue
        time.sleep(1)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def find_payload_root(extracted: Path) -> Path:
    children = [p for p in extracted.iterdir() if p.name != "__MACOSX"]
    if len(children) == 1 and children[0].is_dir():
        candidate = children[0]
        if (candidate / "app.py").exists() or (candidate / "VERSION.txt").exists():
            return candidate
    return extracted


def backup_state(version: str) -> Path:
    BACKUPS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUPS / f"before_{version}_{stamp}"
    dest.mkdir(parents=True)
    if (ROOT / "data").exists():
        shutil.copytree(ROOT / "data", dest / "data", dirs_exist_ok=True)
    for file_name in [".env", "VERSION.txt", "requirements.txt"]:
        src = ROOT / file_name
        if src.exists():
            shutil.copy2(src, dest / file_name)
    code = dest / "code"
    code.mkdir()
    for item in ROOT.iterdir():
        if item.name in PRESERVE_NAMES or item.name in {"backups", "__pycache__"}:
            continue
        if item.name.endswith(".zip"):
            continue
        target = code / item.name
        try:
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            elif item.is_file():
                shutil.copy2(item, target)
        except Exception:
            pass
    return dest


def install_payload(payload: Path) -> None:
    for item in list(ROOT.iterdir()):
        if item.name in PRESERVE_NAMES or item.name in PRESERVE_FILES or item.name == "__pycache__":
            continue
        if item.resolve() == Path(__file__).resolve():
            continue
        try:
            if item.is_dir():
                shutil.rmtree(item)
            elif item.is_file():
                item.unlink()
        except Exception:
            pass

    for item in payload.iterdir():
        if item.name in PRESERVE_NAMES or item.name in PRESERVE_FILES or item.name == "__pycache__":
            continue
        target = ROOT / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        elif item.is_file():
            shutil.copy2(item, target)


def rollback(backup: Path) -> None:
    code = backup / "code"
    if code.exists():
        for item in code.iterdir():
            target = ROOT / item.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    target.unlink(missing_ok=True)
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
    data_backup = backup / "data"
    if data_backup.exists():
        shutil.copytree(data_backup, ROOT / "data", dirs_exist_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait-pid", type=int, default=0)
    args = ap.parse_args()
    print("Investment Committee Copilot - Updater")
    print("현재 앱이 종료될 때까지 기다리는 중...")
    wait_for_pid(args.wait_pid)
    if not PENDING.exists():
        print("대기 중인 업데이트 정보가 없습니다.")
        input("Enter를 누르면 닫습니다...")
        return 1
    pending = json.loads(PENDING.read_text(encoding="utf-8"))
    version = str(pending.get("version") or "unknown")
    zip_path = Path(str(pending.get("zip_path") or ""))
    expected = str(pending.get("sha256") or "").lower().strip()
    if not zip_path.exists():
        print("업데이트 ZIP을 찾을 수 없습니다:", zip_path)
        input("Enter를 누르면 닫습니다...")
        return 1
    if expected and sha256(zip_path) != expected:
        print("SHA-256 검증 실패. 업데이트를 중단합니다.")
        input("Enter를 누르면 닫습니다...")
        return 1

    backup = backup_state(version)
    print("백업 완료:", backup)
    try:
        with tempfile.TemporaryDirectory(prefix="ic_update_") as td:
            td = Path(td)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(td)
            payload = find_payload_root(td)
            if not (payload / "app.py").exists():
                raise RuntimeError("업데이트 패키지에 app.py가 없습니다.")
            install_payload(payload)

        python = ROOT / ".venv" / "Scripts" / "python.exe"
        if python.exists() and (ROOT / "requirements.txt").exists():
            print("Python 패키지 동기화 중...")
            rc = subprocess.call([str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt"), "--disable-pip-version-check"])
            if rc != 0:
                raise RuntimeError(f"패키지 동기화 실패 (code {rc})")

        PENDING.unlink(missing_ok=True)
        print(f"업데이트 완료: {version}")
        print("앱을 다시 시작합니다...")
        subprocess.Popen(["cmd", "/c", "start", "", str(ROOT / "START_HERE.bat")], cwd=str(ROOT))
        time.sleep(2)
        return 0
    except Exception as exc:
        print("업데이트 실패:", exc)
        print("이전 버전으로 복구 중...")
        try:
            rollback(backup)
            print("복구 완료.")
        except Exception as rex:
            print("자동 복구에도 문제가 발생했습니다:", rex)
        input("Enter를 누르면 닫습니다...")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
