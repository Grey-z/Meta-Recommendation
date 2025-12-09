from openai import AzureOpenAI
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Azure OpenAI 配置
azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "https://agenthiack.openai.azure.com/")
api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
deployment_name = "gpt-4.1"

# 从环境变量读取 API Key
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is not set")

client = AzureOpenAI(
    api_key=api_key,
    azure_endpoint=azure_endpoint,
    api_version=api_version
)


SYSTEM_PROMPT = (
    "你是一个擅长用户意图识别和工具规划的agent。输入可能是结构化字段或自然语言描述。"
    "你的唯一输出是: 为后续检索需要调用哪些工具 (小红书, Google Maps) 以及每次调用的 query 参数, 且仅以规定的形式输出。\n\n"
    "[可用工具]\n"
    "1) xhs.search (小红书): 获取口碑/探店/氛围/口味线索。参数: query:string。\n"
    "2) gmap.search (Google Maps): 获取候选门店列表, 评分, 价格区间, 评论, 营业时间等。参数: query:string。\n\n"
    "[用户输入解析]\n"
    "可能包含:\n"
    "- <restaurant_type>: 例如{casual, fine dining, fast casual, street food, buffet, cafe}\n"
    "- <flavor_profile>: 例如{spicy, savory, sweet, sour, umami, mild}\n"
    "- <dining_purpose>: 例如{any, date night, family, business, solo, friends, celebration}\n"
    "- <budget_range>: 例如 20-60 SGD per person\n"
    "- <location>: 例如 Chinatown\n"
    "- <food_type>: 例如 Hotpot, BBQ, Seafood, Dim Sum\n\n"
    "[输出要求]\n"
    "- 仅按照[输出格式示例]的形式输出所选工具与参数, 不要返回除工具调用外的任何文字或解释。\n"
    "- 若 <restaurant_type> 或 <food_type> 含多项, 可分别为每一项各调用一次 gmap.search 与 xhs.search。\n"
    "- 若信息不足, 基于已有字段做最合理的关键词组合; 不要向用户追问。\n\n"
    "[输出格式示例]\n"
    "[\n"
    "  {\"function_name\": \"gmap.search\", \"parameters\": {\"query\": \"Chinatown Hotpot buffet\"}},\n"
    "  {\"function_name\": \"xhs.search\", \"parameters\": {\"query\": \"新加坡 Chinatown 川菜 辣 朋友聚餐 人均 20-60\"}}\n"
    "]\n"
)

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
                        "description": "搜索关键词，严格遵守<location><food_type><restaurant_type>，如：\"Chinatown Hotpot buffet\"。"
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
            "name": "xhs.search",
            "description": "在小红书搜索真实探店/口碑/氛围与口味线索, 辅助验证匹配度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "中英混合关键词, 包含城市/商圈 + 菜系/口味 + 场景 + 预算, 例如: '新加坡 Chinatown 川菜 辣 朋友聚餐 人均 20-60'。"
                    }
                },
                "required": ["query"],
                "additionalProperties": False
            }
        }
    }
]

def run_demo(user_input: str):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_input},
    ]

    completion = client.chat.completions.create(
        model=deployment_name,
        temperature=0.2,
        messages=messages,
        tools=TOOLS,
    )

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

    resp = run_demo(example_input)
    # 打印第一条消息以便查看是否产生 function call
    first_choice = resp.choices[0].message
    print(first_choice)