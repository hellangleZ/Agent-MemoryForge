# -*- coding: utf-8 -*-
"""
Redis辅助函数单元测试
"""

import json
from utils.redis_helper import RedisHelper, EnhancedJSONEncoder


class TestEnhancedJSONEncoder:
    """测试增强JSON编码器"""

    def test_encode_set(self):
        """测试集合编码"""
        data = {"set": {1, 2, 3}}
        EnhancedJSONEncoder()
        result = json.dumps(data, cls=EnhancedJSONEncoder)
        assert "set" in result
        assert "[1, 2, 3]" in result

    def test_encode_complex_object(self):
        """测试复杂对象编码"""

        class TestObj:
            def __init__(self):
                self.value = 42

        obj = TestObj()
        result = json.dumps({"obj": obj}, cls=EnhancedJSONEncoder)
        assert "value" in result
        assert "42" in result


class TestRedisHelper:
    """测试Redis辅助类"""

    def test_serialize_string(self):
        """测试字符串序列化"""
        result = RedisHelper.serialize("test")
        assert isinstance(result, bytes)
        assert result == b"test"

    def test_serialize_dict(self):
        """测试字典序列化"""
        data = {"key": "value", "number": 42}
        result = RedisHelper.serialize(data)
        assert isinstance(result, bytes)
        assert b"key" in result
        assert b"value" in result

    def test_serialize_bytes(self):
        """测试字节序列化"""
        data = b"test_bytes"
        result = RedisHelper.serialize(data)
        assert result == data

    def test_deserialize_json(self):
        """测试JSON反序列化"""
        data = b'{"key": "value", "number": 42}'
        result = RedisHelper.deserialize(data)
        assert isinstance(result, dict)
        assert result["key"] == "value"
        assert result["number"] == 42

    def test_deserialize_string(self):
        """测试字符串反序列化"""
        data = b"plain_string"
        result = RedisHelper.deserialize(data)
        assert result == "plain_string"

    def test_serialize_deserialize_roundtrip(self):
        """测试序列化/反序列化往返"""
        original = {
            "string": "test",
            "number": 42,
            "float": 3.14,
            "bool": True,
            "null": None,
            "list": [1, 2, 3],
            "dict": {"nested": "value"},
        }
        serialized = RedisHelper.serialize(original)
        deserialized = RedisHelper.deserialize(serialized)
        assert deserialized == original


class TestCreateConnectionPool:
    """测试连接池创建"""

    def test_create_pool_defaults(self):
        """测试使用默认参数创建连接池"""
        pool = RedisHelper.create_connection_pool()
        assert pool is not None
        # 注意：不实际连接Redis，只验证创建逻辑

    def test_create_pool_custom_params(self):
        """测试使用自定义参数创建连接池"""
        pool = RedisHelper.create_connection_pool(
            host="custom_host", port=6380, db=1, max_connections=50
        )
        assert pool is not None
