import asyncio
import logging


from utils import logger as logger_utils
from utils import retry_helper


def test_retry_request_retries(monkeypatch):
    calls = {"count": 0}

    def _sleep(_):
        return None

    monkeypatch.setattr(retry_helper.time, "sleep", _sleep)

    @retry_helper.retry_request(max_retries=2, base_delay=0.01, max_delay=0.02)
    def flaky():
        calls["count"] += 1
        if calls["count"] == 1:
            raise retry_helper.requests.exceptions.RequestException("fail")
        return "ok"

    assert flaky() == "ok"
    assert calls["count"] == 2


def test_retry_async_request_retries(monkeypatch):
    calls = {"count": 0}

    async def _sleep(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", _sleep)

    @retry_helper.retry_async_request(max_retries=2, base_delay=0.01, max_delay=0.02)
    async def flaky():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("boom")
        return "ok"

    result = asyncio.run(flaky())
    assert result == "ok"
    assert calls["count"] == 2


def test_setup_logging_with_file(tmp_path):
    log_file = tmp_path / "app.log"
    logger = logger_utils.setup_logging("test", level="INFO", log_file=str(log_file))
    logger.info("hello")
    assert log_file.exists()
    assert "hello" in log_file.read_text(encoding="utf-8")


def test_get_logger_creates_default():
    logger = logger_utils.get_logger("new_logger")
    assert isinstance(logger, logging.Logger)
    assert logger.handlers
