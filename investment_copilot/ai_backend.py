from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from openai import AsyncOpenAI
from agents import OpenAIChatCompletionsModel

from .config import DATA_DIR

AI_CONFIG_PATH = DATA_DIR / "ai_config.json"
DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:1234/v1"
AIMode = Literal["LOCAL", "HYBRID", "CLOUD"]


@dataclass
class AIConfig:
    mode: AIMode = "LOCAL"
    local_base_url: str = DEFAULT_LOCAL_BASE_URL
    local_model: str = ""


def _normalize_base_url(value: str) -> str:
    url = (value or DEFAULT_LOCAL_BASE_URL).strip().rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    return url


def load_ai_config() -> AIConfig:
    if not AI_CONFIG_PATH.exists():
        return AIConfig()
    try:
        raw = json.loads(AI_CONFIG_PATH.read_text(encoding="utf-8"))
        mode = str(raw.get("mode") or "LOCAL").upper()
        if mode not in {"LOCAL", "HYBRID", "CLOUD"}:
            mode = "LOCAL"
        return AIConfig(
            mode=mode,  # type: ignore[arg-type]
            local_base_url=_normalize_base_url(str(raw.get("local_base_url") or DEFAULT_LOCAL_BASE_URL)),
            local_model=str(raw.get("local_model") or "").strip(),
        )
    except Exception:
        return AIConfig()


def save_ai_config(config: AIConfig) -> None:
    AI_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(config)
    data["local_base_url"] = _normalize_base_url(config.local_base_url)
    AI_CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_local_models(base_url: str = DEFAULT_LOCAL_BASE_URL, timeout: int = 3) -> list[str]:
    url = _normalize_base_url(base_url) + "/models"
    req = urllib.request.Request(url, headers={"User-Agent": "InvestmentCommitteeCopilot/0.3"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8-sig"))
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(
            f"LM Studio 로컬 서버에 연결할 수 없습니다 ({reason}). "
            "LM Studio에서 모델을 로드하고 Developer > Start server를 켜세요."
        ) from exc
    except Exception as exc:
        raise RuntimeError(f"LM Studio 모델 목록을 읽지 못했습니다: {exc}") from exc

    models = []
    for item in payload.get("data", []):
        model_id = str(item.get("id") or "").strip()
        if model_id:
            models.append(model_id)
    return models


def resolve_local_model(config: AIConfig) -> str:
    models = list_local_models(config.local_base_url)
    if config.local_model and config.local_model in models:
        return config.local_model
    if len(models) == 1:
        return models[0]
    if not models:
        raise RuntimeError(
            "LM Studio 서버는 응답하지만 로드된 모델이 없습니다. "
            "LM Studio에서 7~8B Q4 모델을 로드한 뒤 다시 실행하세요."
        )
    if config.local_model and config.local_model not in models:
        raise RuntimeError(
            f"설정된 로컬 모델 '{config.local_model}'이 현재 로드되어 있지 않습니다. "
            f"사용 가능한 모델: {', '.join(models)}"
        )
    raise RuntimeError(
        "LM Studio에 여러 모델이 로드되어 있습니다. 설정 메뉴에서 사용할 로컬 모델을 선택하세요."
    )


def build_local_model(config: AIConfig) -> OpenAIChatCompletionsModel:
    model_id = resolve_local_model(config)
    client = AsyncOpenAI(
        base_url=_normalize_base_url(config.local_base_url),
        api_key="lm-studio",
    )
    return OpenAIChatCompletionsModel(model=model_id, openai_client=client)


def needs_openai_api(mode: str) -> bool:
    return str(mode).upper() in {"HYBRID", "CLOUD"}
