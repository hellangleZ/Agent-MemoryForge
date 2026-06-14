"""
LTM偏好Key映射配置
将用户友好的key映射到数据库key
"""

from typing import Dict

# Key映射表
KEY_MAPPING: Dict[str, str] = {
    # 中文keys
    "管理风格": "work_decision_making_style",
    "沟通风格": "communication_style",
    "会议风格": "meeting_time_preference",
    "风险管理": "risk_management",
    "工作风格": "work_decision_making_style",
    "决策风格": "work_decision_making_style",
    # 英文keys (LLM可能生成的)
    "management_style": "work_decision_making_style",
    "communication_style": "communication_style",
    "meeting_style": "meeting_time_preference",
    "meeting_preference": "meeting_time_preference",
    "risk_management": "risk_management",
    "risk_management_style": "risk_management",
    "decision_making": "work_decision_making_style",
    "work_style": "work_decision_making_style",
    "leadership_style": "work_decision_making_style",
}


def resolve_key(user_key: str) -> str:
    """
    解析用户输入的key到数据库key

    Args:
        user_key: 用户输入的key（可以是中文或英文）

    Returns:
        数据库中的实际key

    Examples:
        >>> resolve_key("管理风格")
        "work_decision_making_style"
        >>> resolve_key("management_style")
        "work_decision_making_style"
    """
    return KEY_MAPPING.get(user_key, user_key)


def add_mapping(user_key: str, db_key: str) -> None:
    """
    添加新的key映射

    Args:
        user_key: 用户key
        db_key: 数据库key
    """
    KEY_MAPPING[user_key] = db_key


def get_all_mappings() -> Dict[str, str]:
    """
    获取所有key映射

    Returns:
        映射字典的副本
    """
    return KEY_MAPPING.copy()
