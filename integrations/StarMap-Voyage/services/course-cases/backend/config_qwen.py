import os


# config_qwen.py

def get_qwen_config():
    """
    返回Qwen模型的LLM配置列表
    """
    api_key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
    if api_key:
        return [
            {
                "model": os.environ.get("SILICONFLOW_LLM_MODEL", "Qwen/Qwen2.5-72B-Instruct"),
                "api_key": api_key,
                "base_url": os.environ.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
                "api_type": "openai",
            }
        ]

    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("请先设置 SILICONFLOW_API_KEY 或 DASHSCOPE_API_KEY 环境变量。")

    return [
        {
            "model": os.environ.get("DASHSCOPE_CHAT_MODEL", "qwen-plus"),
            "api_key": api_key,
            "base_url": os.environ.get(
                "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
            ),
            "api_type": "openai",
        }
    ]
