"""验证无问芯穹 API 是否可用"""

import asyncio
from .llm_client import LLMClient


async def test_api():
    """测试多个模型的 API 连通性"""
    base_url = "https://cloud.infini-ai.com/maas/v1"
    api_key = "sk-q2pj7bhakykp3z44"

    models_to_test = [
        ("glm-5.1", "GM/摘要模型"),
        ("deepseek-v4-flash", "玩家模型(flash)"),
        ("kimi-k2.6", "玩家模型"),
        ("deepseek-v4-pro", "玩家模型(pro)"),
        ("gpt-5.4", "玩家模型"),
        ("minimax-m2.7", "玩家模型"),
    ]

    for model, desc in models_to_test:
        print(f"\n--- 测试 {model} ({desc}) ---")
        client = LLMClient(base_url=base_url, api_key=api_key, model=model)

        try:
            result = await client.call_json(
                messages=[
                    {"role": "user", "content": "请回复一个JSON格式的消息：{\"status\": \"ok\", \"message\": \"连接成功\"}"},
                ],
                temperature=0.1,
            )
            print(f"  [成功] 响应: {result}")
        except Exception as e:
            print(f"  [失败] 错误类型: {type(e).__name__}, 信息: {str(e)[:200]}")

        await client.close()
        # 请求间隔避免限速
        await asyncio.sleep(2)

    print("\n--- 所有测试完成 ---")


if __name__ == "__main__":
    asyncio.run(test_api())