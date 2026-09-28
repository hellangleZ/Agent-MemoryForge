"""Minimal TypeSafe (Jev) System One client.

Jev is a decision model: send a state + typed questions, get structured answers.
This wrapper exposes the three primitives (choice/score/noul) over plain HTTP so
memory-layer decision points can use it without pulling in the official SDK.

Config (env):
  TYPESAFE_API_KEY   - required; when unset the client is disabled (available()=False)
  TYPESAFE_BASE_URL  - default https://api.typesafe.ai
  TYPESAFE_MODEL     - default jev-latest
  TYPESAFE_TIMEOUT   - seconds, default 5 (System One calls are fast)
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests

from utils.logging_config import get_logger


logger = get_logger(__name__)


class TypeSafeClient:
    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("TYPESAFE_API_KEY") or "").strip()
        self.base_url = (base_url or os.getenv("TYPESAFE_BASE_URL") or "https://api.typesafe.ai").rstrip("/")
        self.model = (model or os.getenv("TYPESAFE_MODEL") or "jev-latest").strip()
        try:
            self.timeout = float(timeout if timeout is not None else (os.getenv("TYPESAFE_TIMEOUT") or "5"))
        except Exception:
            self.timeout = 5.0

    def available(self) -> bool:
        return bool(self.api_key)

    def _post(self, *, state: str, questions: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/systemone"
        body = {"state": state, "model": self.model, "questions": questions}
        resp = requests.post(
            url,
            json=body,
            timeout=self.timeout,
            headers={
                "authorization": f"Bearer {self.api_key}",
                "content-type": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()

    def decide(self, *, state: str, questions: Dict[str, Any]) -> Dict[str, Any]:
        """Run one System One evaluation. Returns the parsed answers map.

        Raises on HTTP/transport errors so callers can apply their own fallback.
        """
        if not self.available():
            raise RuntimeError("TypeSafe client is not configured (TYPESAFE_API_KEY missing)")
        payload = self._post(state=state, questions=questions)
        answers = payload.get("answers")
        if not isinstance(answers, dict):
            raise RuntimeError("TypeSafe response missing answers")
        return answers

    # ---- question builders (keep call sites readable) ----

    @staticmethod
    def choice(*, instructions: str, criteria: Dict[str, Any]) -> Dict[str, Any]:
        return {"type": "choice", "instructions": instructions, "criteria": criteria}

    @staticmethod
    def score(*, instructions: str, criteria: List[Any]) -> Dict[str, Any]:
        return {"type": "score", "instructions": instructions, "criteria": criteria}

    @staticmethod
    def noul(*, instructions: str, criteria: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        q: Dict[str, Any] = {"type": "noul", "instructions": instructions}
        if criteria:
            q["criteria"] = criteria
        return q
