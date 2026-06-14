# -*- coding: utf-8 -*-
"""
Redis辅助函数
统一Redis数据序列化和反序列化
"""

import json
import logging
from typing import Any
import redis

logger = logging.getLogger(__name__)


class EnhancedJSONEncoder(json.JSONEncoder):
    """增强的JSON编码器，支持更多数据类型"""

    def default(self, obj):
        if isinstance(obj, set):
            return list(obj)
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        return super().default(obj)


class RedisHelper:
    """Redis辅助类，提供统一的序列化/反序列化接口"""

    @staticmethod
    def serialize(data: Any) -> bytes:
        """
        统一序列化逻辑

        Args:
            data: 要序列化的数据

        Returns:
            bytes: 序列化后的字节数据
        """
        try:
            if isinstance(data, bytes):
                return data
            if isinstance(data, str):
                return data.encode("utf-8")
            if isinstance(data, (dict, list, int, float, bool, type(None))):
                return json.dumps(data, cls=EnhancedJSONEncoder).encode("utf-8")
            return str(data).encode("utf-8")
        except Exception as e:
            logger.error(f"序列化失败: {e}, 数据类型: {type(data)}")
            raise

    @staticmethod
    def deserialize(data: bytes) -> Any:
        """
        统一反序列化逻辑

        Args:
            data: 要反序列化的字节数据

        Returns:
            Any: 反序列化后的数据
        """
        try:
            if isinstance(data, bytes):
                data = data.decode("utf-8")

            # 尝试解析为JSON
            try:
                return json.loads(data)
            except (json.JSONDecodeError, TypeError):
                # 不是JSON，返回字符串
                return data
        except Exception as e:
            logger.error(f"反序列化失败: {e}")
            raise

    @staticmethod
    def create_connection_pool(
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        max_connections: int = 20,
        decode_responses: bool = False,
    ) -> redis.ConnectionPool:
        """
        创建Redis连接池

        Args:
            host: Redis主机
            port: Redis端口
            db: 数据库编号
            max_connections: 最大连接数
            decode_responses: 是否自动解码响应

        Returns:
            redis.ConnectionPool: 连接池对象
        """
        pool = redis.ConnectionPool(
            host=host,
            port=port,
            db=db,
            max_connections=max_connections,
            decode_responses=decode_responses,
        )
        logger.info(
            f"Redis连接池创建成功: {host}:{port}, DB={db}, 最大连接数={max_connections}"
        )
        return pool

    @staticmethod
    def get_redis_client(
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        max_connections: int = 20,
    ) -> redis.Redis:
        """
        获取Redis客户端（使用连接池）

        Args:
            host: Redis主机
            port: Redis端口
            db: 数据库编号
            max_connections: 最大连接数

        Returns:
            redis.Redis: Redis客户端
        """
        pool = RedisHelper.create_connection_pool(
            host=host,
            port=port,
            db=db,
            max_connections=max_connections,
            decode_responses=False,  # 统一使用二进制模式
        )
        return redis.Redis(connection_pool=pool)
