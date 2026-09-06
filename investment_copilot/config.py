from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
load_dotenv(BASE_DIR / ".env")
os.environ.setdefault("OPENAI_AGENTS_DISABLE_TRACING", "1")


@dataclass(frozen=True)
class Settings:
    main_model: str = os.getenv("OPENAI_MODEL_MAIN", "gpt-5.6-sol")
    fast_model: str = os.getenv("OPENAI_MODEL_FAST", "gpt-5.6-terra")
    price_history_years: int = int(os.getenv("PRICE_HISTORY_YEARS", "5"))
    risk_free_rate_pct: float = float(os.getenv("RISK_FREE_RATE_PCT", "3.0"))
    database_path: Path = DATA_DIR / "copilot.db"
    service_name: str = "investment-copilot"


settings = Settings()
