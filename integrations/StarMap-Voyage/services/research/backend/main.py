"""Research-Copilot-OS 启动入口"""

import argparse
import os
import sys
import uvicorn


def main():
    # Windows 控制台默认 GBK 无法打印 emoji，切换为 UTF-8 输出避免 UnicodeEncodeError
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Research-Copilot-OS 科研智能副驾平台")
    parser.add_argument("--host", default="127.0.0.1", help="服务地址")
    parser.add_argument("--port", type=int, default=8000, help="服务端口")
    parser.add_argument("--api-key", default="", help="DeepSeek API Key")
    parser.add_argument("--model", default="deepseek-chat", help="LLM 模型名称")
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")

    args = parser.parse_args()

    # 设置 API Key
    if args.api_key:
        os.environ["DEEPSEEK_API_KEY"] = args.api_key

    if not os.getenv("DEEPSEEK_API_KEY"):
        print("⚠️  未设置 DEEPSEEK_API_KEY 环境变量")
        print("   可通过 --api-key 参数或环境变量设置")
        print("   export DEEPSEEK_API_KEY=sk-xxxx")

    print(f"""
╔══════════════════════════════════════════════╗
║     🧪 Research-Copilot-OS v0.1.0           ║
║     AI 赋能科研全流程平台                      ║
╚══════════════════════════════════════════════╝

  后端 API:  http://{args.host}:{args.port}
  API 文档:  http://{args.host}:{args.port}/docs
  LLM:       {args.model}

  启动前端:  streamlit run frontend/app.py

  功能列表:
  📄 1. 单论文解读    📚 2. 多论文综述
  🧩 3. 代码分块      🔀 4. 模块迁移
  📊 5. 数据集适配    🎨 6. 数据增强
  📈 7. 可视化生成    🧪 8. 消融实验
  🎛️ 9. 超参数调优    📋 10. 实验记录

  按 Ctrl+C 停止服务
""")

    uvicorn.run(
        "backend.api.routes:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
