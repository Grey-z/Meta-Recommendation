from openai import AzureOpenAI, OpenAI
import os
from pathlib import Path
from dotenv import load_dotenv
from typing import Union

from llm_usage import record_response_usage

# 加载 .env 文件
DEPLOYMENT_NAME = "gpt-4.1"

# 从环境变量读取 API Key


SYSTEM_PROMPT = """你是一个擅长用户意图识别和工具规划的agent。输入可能是结构化字段或自然语言描述。
你的唯一输出是: 为后续检索需要调用哪些工具 (小红书, Google Maps, Yelp) 以及每次调用的 query 参数, 且仅以规定的形式输出。

[位置处理原则]
- **默认位置策略**：如果用户输入中未明确指定城市或国家（例如仅提到 "Chinatown" 或未提及地点），必须默认以 **新加坡 (Singapore)** 作为地理背景。
- 对于 `xhs.search` 和 `gmap.search`，地理位置信息必须直接包含在 `query` 字符串内。
- 对于 `yelp.search`，地理位置信息应放入专门的 `location` 参数中。

[可用工具]
1) xhs.search (小红书): 获取口碑/探店/氛围/口味线索。参数: query:string (需包含地点关键词)。
2) gmap.search (Google Maps): 获取候选门店列表, 评分, 价格区间, 评论, 营业时间等。参数: query:string (需包含地点关键词)。
3) yelp.search (Yelp): 获取候选门店列表, 评分, 价格区间, 评论, 营业时间等。参数: query:string, location:string。

[用户输入解析]
可能包含:
- <restaurant_type>: 例如{casual, fine dining, fast casual, street food, buffet, cafe}
- <flavor_profile>: 例如{spicy, savory, sweet, sour, umami, mild}
- <dining_purpose>: 例如{any, date night, family, business, solo, friends, celebration}
- <budget_range>: 例如 20-60 SGD per person
- <location>: 例如 Chinatown (若为空，默认为 Singapore)
- <food_type>: 例如 Hotpot, BBQ, Seafood, Dim Sum

[输出要求]
- 仅按照[输出格式示例]的形式输出所选工具与参数, 不要返回除工具调用外的任何文字或解释。
- 若信息不足, 基于已有字段做最合理的关键词组合; 不要向用户追问。

[输出格式示例]
[
  {"function_name": "gmap.search", "parameters": {"query": "Singapore Chinatown Hotpot buffet"}},
  {"function_name": "yelp.search", "parameters": {"query": "Hotpot buffet", "location": "Singapore, Chinatown"}},
  {"function_name": "xhs.search", "parameters": {"query": "新加坡 Chinatown 川菜 辣 朋友聚餐 人均 20-60"}}
]"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "gmap.search",
            "description": "在 Google Maps 中搜索餐厅候选, 返回门店列表、评分、价格区间、评论、营业时间等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词。必须包含地点（若用户未指定，默认包含'Singapore'）+ 菜系 + 类型，如：'Singapore Chinatown Hotpot buffet'。"
                    }
                },
                "required": ["query"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "yelp.search",
            "description": "在 Yelp 中搜索餐厅候选, 返回门店列表、评分、价格区间、评论、营业时间等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，包含菜系与餐厅类型，如：'Hotpot buffet'。"
                    },
                    "location": {
                        "type": "string",
                        "description": "地理位置。若用户未明确指定城市，必须默认为 'Singapore' 或 'Singapore, <具体商圈>'。"
                    }
                },
                "required": ["query", "location"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "xhs.search",
            "description": "在小红书搜索真实探店/口碑/氛围与口味线索, 辅助验证匹配度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "中英混合关键词。必须包含城市名（默认'新加坡'）+ 地点/商圈 + 菜系 + 场景 + 预算。例如：'新加坡 Chinatown 川菜 约会 人均 50'。"
                    }
                },
                "required": ["query"],
                "additionalProperties": False
            }
        }
    }
]

def run_demo(
        client: Union[AzureOpenAI, OpenAI],
        user_input: str,
        model: str = DEPLOYMENT_NAME, # default
    ):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_input},
    ]

    completion = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=messages,
        tools=TOOLS,
    )
    record_response_usage(completion, model)

    return completion


if __name__ == "__main__":
    example_input = (
        "用户输入:\n"
        "{\n"
        "  \"Restaurant Type\": \"Restaurant\",\n"
        "  \"Flavor Profile\": \"Spicy\",\n"
        "  \"Dining Purpose\": \"Friends\",\n"
        "  \"Budget Range (per person)\": \"20 to 60 (SGD)\",\n"
        "  \"Location (Singapore)\": \"Chinatown\",\n"
        "  \"Food Type\": \"Sichuan food\"\n"
        "}"
    )

    env_path = Path(__file__).parent.parent / '.env'
    load_dotenv(dotenv_path=env_path)

    from client import create_agent_sync_client

    client, _summary_model, planning_model = create_agent_sync_client()

    resp = run_demo(client, example_input, planning_model or DEPLOYMENT_NAME)
    # 打印第一条消息以便查看是否产生 function call
    first_choice = resp.choices[0].message
    print(first_choice)
