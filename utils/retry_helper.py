# -*- coding: utf-8 -*-
"""
网络请求重试机制
"""

import time
import functools
import logging
from typing import Callable, Any, Type, Tuple
import requests

logger = logging.getLogger(__name__)


def retry_request(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    exceptions: Tuple[Type[Exception], ...] = (requests.exceptions.RequestException,),
):
    """
    网络请求重试装饰器

    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟时间(秒)
        max_delay: 最大延迟时间(秒)
        exceptions: 需要重试的异常类型

    Returns:
        装饰器函数
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_retries - 1:
                        logger.error(
                            f"{func.__name__} 失败，已达最大重试次数 {max_retries}"
                        )
                        raise

                    # 计算指数退避延迟
                    delay = min(base_delay * (2**attempt), max_delay)
                    logger.warning(
                        f"{func.__name__} 失败 (尝试 {attempt + 1}/{max_retries}): {e}. "
                        f"等待 {delay:.1f}秒 后重试..."
                    )
                    time.sleep(delay)

            raise last_exception

        return wrapper

    return decorator


def retry_async_request(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
):
    """
    异步网络请求重试装饰器

    Args:
        max_retries: 最大重试次数
        base_delay: 基础延迟时间(秒)
        max_delay: 最大延迟时间(秒)

    Returns:
        装饰器函数
    """
    import asyncio

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e

                    if attempt == max_retries - 1:
                        logger.error(
                            f"{func.__name__} 失败，已达最大重试次数 {max_retries}"
                        )
                        raise

                    # 计算指数退避延迟
                    delay = min(base_delay * (2**attempt), max_delay)
                    logger.warning(
                        f"{func.__name__} 失败 (尝试 {attempt + 1}/{max_retries}): {e}. "
                        f"等待 {delay:.1f}秒 后重试..."
                    )
                    await asyncio.sleep(delay)

            raise last_exception

        return wrapper

    return decorator
