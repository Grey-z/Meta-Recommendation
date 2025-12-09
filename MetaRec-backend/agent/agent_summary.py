from openai import AzureOpenAI
import os
import json
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
# 从当前文件向上查找 MetaRec-backend 目录中的 .env 文件
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)
import glob
from typing import Any, Dict, List, Union
import logging
from datetime import datetime

# Azure OpenAI 配置
deployment_name = "o4-mini"  # Azure 部署名称

# 从环境变量读取配置
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is not set")

# Azure OpenAI 端点和 API 版本
azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "https://agenthiack.openai.azure.com/")
api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

client = AzureOpenAI(
    api_key=api_key,
    azure_endpoint=azure_endpoint,
    api_version=api_version
)

# 模块级 logger，作为库被调用时不主动配置处理器
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SYSTEM_PROMPT = (
    "你是一个善于分析与总结、推荐与排序的智能体。"
    "任务: 根据【用户偏好输入】与【工具检索结果】进行候选集融合、去重、评分与排序, 输出5个最匹配的餐厅。\n\n"
    "[处理步骤]\n"
    "1) 标准化与补全: 统一币种为 SGD; 将价位符号映射为区间; 标准化菜系/口味/food_type; 从摘要中抽取场景线索 (适合聚会/约会/亲子/安静等)。\n"
    "2) 去重: 按 name + 地址/坐标近似去重; 品牌多分店按距离与评分择优。\n"
    "3) 约束过滤 (硬条件优先):\n"
    "   - 预算: 若存在 budget_max, 剔除明显高出 >15% 的候选; 若仅给预算符号, 按区间中位估算; 无法判定时保留但降低分。\n"
    "   - 地点: 优先同商圈; 若不足再放宽到同城区/整座城市, 并在结果中标注距离/通达性。\n"
    "   - 饮食禁忌 (如 halal/vegetarian): 严格过滤不匹配项。\n"
    "4) 评分与排序 (0–100):\n"
    "   - 匹配度 (40%): 口味/food_type/餐厅类型/用餐场景与用户偏好契合度。\n"
    "   - 质量 (30%): Google 评分与评论量加权 (示例: score = rating*10 + log1p(reviews_count)*2, 上限约50); 最近一年口碑 (小红书/评论) 一致性加分。\n"
    "   - 价格适配 (15%): 落在预算区间得满分; 轻微超预算 ≤15% 减半; 超出 >15% 降为 0。\n"
    "   - 可达性与可用性 (15%): 距离/步行时间、是否 open now/容易订位、营业至晚等。\n"
    "   同分优先级: 更高评分且评论量更大者; 其次交通更便捷者; 再次多样性 (覆盖不同子品类)。\n"
    "5) 解释与不确定性: 为每条结果提供 1–2 句“为什么匹配”的可验证理由; 若信息缺失 (如价位不明), 明确指出并给出依据。\n\n"
    "[输出格式 (必须严格遵守, 仅输出 JSON, 不要额外文字)]\n"
    "{\n  \"recommendations\": [\n    {\n      \"name\": \"...\",\n      \"address\": \"...\",\n      \"area\": \"...\",\n      \"cuisine\": \"Sichuan/Hotpot/BBQ/...\",\n      \"type\": \"casual/fine dining/...\",\n      \"price_per_person_sgd\": \"30-50\",\n      \"rating\": 4.6,\n      \"reviews_count\": 1234,\n      \"open_hours_note\": \"Open late Fri\",\n      \"flavor_match\": [\"Spicy\", \"Umami\"],\n      \"purpose_match\": [\"Friends\", \"Group-friendly\"],\n      \"why\": \"基于评分与评论量、重辣口味与朋友聚会标签, 且人均落在预算内。\",\n      \"sources\": {\n        \"google_maps\": \"<URL or place_id or snippet>\",\n        \"xiaohongshu\": \"<note ids or summary if any>\"\n      }\n    }\n  ]\n}\n"
    "- 始终返回正好 5 条 (不足则返回现有并在 why 中说明样本不足)。\n"
    "- 字段缺失用 null 或省略, 不可捏造。\n"
    "- 绝不输出除 JSON 以外的任何文本。"
)


def summarize_recommendations(
    user_input: Union[str, Dict[str, Any]],
    gmap_search_results: Any,
    xhs_search_results: Any,
    # temperature: float = 0.2,
):
    if not isinstance(user_input, str):
        try:
            user_input_str = json.dumps(user_input, ensure_ascii=False)
        except Exception:
            user_input_str = str(user_input)
    else:
        user_input_str = user_input

    # 将工具结果压缩为字符串, 防止过长
    def safe_dump(obj: Any) -> str:
        try:
            return json.dumps(obj, ensure_ascii=False)[:200000]
        except Exception:
            return str(obj)[:200000]

    gmap_str = safe_dump(gmap_search_results)
    xhs_str = safe_dump(xhs_search_results)

    user_message = (
        f"【用户偏好输入】为 {user_input_str}\n\n"
        f"【工具检索结果】{{\n  \"gmap.search\": {gmap_str}, \"xhs.search\": {xhs_str}}}"
    )

    completion = client.chat.completions.create(
        model=deployment_name,
        temperature=1,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )

    return completion


if __name__ == "__main__":
    # 仅在独立运行时配置该模块自己的日志系统
    # 使用相对于当前文件的路径，兼容 macOS 和 Linux
    base_dir = Path(__file__).parent
    log_dir = base_dir / "agent_log" / "agent_summary"
    os.makedirs(log_dir, exist_ok=True)
    log_time = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = os.path.join(log_dir, f"agent_summary_{log_time}.log")
    res_filename = os.path.join(log_dir, f"agent_summary_result_{log_time}.json")

    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler = logging.FileHandler(log_filename, encoding='utf-8')
        file_handler.setFormatter(formatter)
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)
        logger.propagate = False

    logger.info("%s", "=" * 60)
    logger.info("agent_summary main started")
    logger.info("log file: %s", log_filename)
    logger.info("result file (to be written): %s", res_filename)
    logger.info("%s", "=" * 60)

    # 尝试自动读取最近一次 demo 结果作为输入
    demo_dir = base_dir / "demo_res_log"
    latest = None
    try:
        files = sorted(glob.glob(os.path.join(demo_dir, "demo_res_*.json")), reverse=True)
        latest = files[0] if files else None
    except Exception as e:
        logger.warning("glob demo results failed: %s", str(e))
        latest = None

    if latest and os.path.exists(latest):
        logger.info("using latest demo result: %s", latest)
        with open(latest, "r", encoding="utf-8") as f:
            data = json.load(f)
        plan_calls = data.get("plan_calls", [])
        executions = data.get("executions", [])
        # 从 executions 中抽取各工具结果
        gmap_results = None
        xhs_results = None
        for item in executions:
            if item.get("tool") == "gmap.search":
                gmap_results = item.get("output")
            if item.get("tool") == "xhs.search":
                xhs_results = item.get("output")
        # 读取 user_input（由 demo_begin.py 保存）
        user_input = data.get("user_input")
        if not user_input:
            user_input = "从 demo_res_log 自动读取（缺失 user_input，已回退占位）"
            logger.warning("user_input missing in demo result, fallback used")
    else:
        # 回退到最简演示
        logger.info("no demo result found, using fallback input")
        user_input = {
            "Restaurant Type": "Restaurant",
            "Flavor Profile": "Spicy",
            "Dining Purpose": "Friends",
            "Budget Range (per person)": "20 to 60 (SGD)",
            "Location (Singapore)": "Chinatown",
            "Food Type": "Sichuan food"
        }
        gmap_results = []
        xhs_results = []

    logger.info("summarizing recommendations...")
    resp = summarize_recommendations(user_input, gmap_results, xhs_results)
    content = resp.choices[0].message.content
    logger.info("summary generated (%d chars)", len(content) if content else 0)
    logger.info("summary output:\n%s", content if content else "<empty>")

    # 保存JSON结果到同目录
    payload: Dict[str, Any] = {
        "user_input": user_input,
        "gmap_results": gmap_results,
        "xhs_results": xhs_results,
        "summary": None
    }
    try:
        parsed = None
        if content:
            try:
                parsed = json.loads(content)
            except Exception:
                parsed = None
        payload["summary"] = parsed if parsed is not None else content

        with open(res_filename, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        logger.info("result JSON written to: %s", res_filename)
    except Exception as e:
        logger.exception("failed to write result JSON: %s", str(e))

    logger.info("%s", "=" * 60)
    logger.info("agent_summary main finished")