import os


# config_qwen.py

def get_qwen_config():
    """
    返回Qwen模型的LLM配置列表
    """
    api_key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("请先设置 SILICONFLOW_API_KEY 环境变量。")

    return [
        {
            "model": "Qwen/Qwen2.5-72B-Instruct",
            "api_key": api_key,
            "base_url": "https://api.siliconflow.cn/v1",
            "api_type": "openai",
        }
    ]
