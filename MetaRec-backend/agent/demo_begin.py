import json
import logging
from datetime import datetime
import os
from typing import Any, Dict, List
import glob

from agent_plan import run_demo
from agent_mcp.agent_google_map import search_google_maps
from agent_mcp.agent_xiaohongshu import search_notes_by_keyword
from agent_summary import summarize_recommendations


# 日志与结果目录
RUN_LOG_DIR = "/root/multiagent_model/demo_run_log"
RES_LOG_DIR = "/root/multiagent_model/demo_res_log"
os.makedirs(RUN_LOG_DIR, exist_ok=True)
os.makedirs(RES_LOG_DIR, exist_ok=True)

# 离线测试开关: 环境变量 OFFLINE_TEST=1 开启
OFFLINE_TEST = os.getenv("OFFLINE_TEST", "1") == "1"

# 生成带时间戳的日志文件
_log_time = datetime.now().strftime("%Y%m%d_%H%M%S")
_run_log_file = os.path.join(RUN_LOG_DIR, f"demo_run_{_log_time}.log")
_res_json_file = os.path.join(RES_LOG_DIR, f"demo_res_{_log_time}.json")

# 配置日志（重置可能已存在的处理器，保证文件写入生效）
root_logger = logging.getLogger()
for h in list(root_logger.handlers):
    root_logger.removeHandler(h)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(_run_log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def parse_planner_output(resp: Any) -> List[Dict[str, Any]]:
    """
    解析规划Agent的输出，兼容两种格式：
    1) OpenAI tools 调用（message.tool_calls）
    2) 消息content中直接输出的 JSON 数组（[{function_name, parameters}])
    返回标准化后的 [{name: str, parameters: dict}] 列表。
    """
    results: List[Dict[str, Any]] = []
    choice = resp.choices[0]
    message = choice.message

    # 记录原始内容（尽量安全可序列化）
    content = getattr(message, "content", None)
    logger.info("Planner raw content: %s", content if isinstance(content, str) else str(content))

    # 优先解析标准 tool_calls
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        logger.info("Planner returned %d tool_calls", len(tool_calls))
        for idx, tc in enumerate(tool_calls, start=1):
            fn = tc.get("function", {}) if isinstance(tc, dict) else getattr(tc, "function", {})
            name = fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)
            arguments = fn.get("arguments") if isinstance(fn, dict) else getattr(fn, "arguments", "{}")
            try:
                params = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
            except Exception:
                params = {}
            results.append({"name": name, "parameters": params or {}})
            logger.info("Parsed tool_call #%d -> name=%s, parameters=%s", idx, name, json.dumps(params, ensure_ascii=False))
        return results

    # 兼容内容为JSON数组的自定义格式
    if isinstance(content, str):
        text = content.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                arr = json.loads(text)
                logger.info("Planner returned JSON array with %d items", len(arr))
                for idx, item in enumerate(arr, start=1):
                    name = item.get("function_name") or item.get("name")
                    params = item.get("parameters") or {}
                    results.append({"name": name, "parameters": params})
                    logger.info("Parsed plan item #%d -> name=%s, parameters=%s", idx, name, json.dumps(params, ensure_ascii=False))
                return results
            except Exception as e:
                logger.warning("Failed to parse planner JSON array: %s", str(e))

    logger.warning("Planner output could not be parsed into tool calls.")
    return results


def dispatch_tool_call(name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    根据工具名分发到具体实现。返回 {tool: name, input: parameters, output: any, success: bool}
    """
    result: Dict[str, Any] = {"tool": name, "input": parameters, "success": False}
    logger.info("Dispatching tool: %s with parameters: %s", name, json.dumps(parameters, ensure_ascii=False))

    try:
        if name == "gmap.search":
            query = parameters.get("query", "")
            output = search_google_maps(query=query, max_results=10)
            result.update({"output": output, "success": output is not None})
            logger.info("gmap.search success=%s, items=%s", result["success"], len(output) if output else 0)
            return result

        if name == "xhs.search":
            query = parameters.get("query", "")
            output = search_notes_by_keyword(keyword=query, max_results=10)
            result.update({"output": output, "success": output is not None})
            logger.info("xhs.search success=%s, items=%s", result["success"], len(output) if output else 0)
            return result

        # 未知工具
        result.update({"error": f"Unknown tool: {name}"})
        logger.warning("Unknown tool encountered: %s", name)
        return result
    except Exception as e:
        result.update({"error": str(e)})
        logger.exception("Tool execution error for %s: %s", name, str(e))
        return result


def load_latest_results() -> Dict[str, Any]:
    files = sorted(glob.glob(os.path.join(RES_LOG_DIR, "demo_res_*.json")), reverse=True)
    latest = files[0] if files else None
    if not latest or not os.path.exists(latest):
        logger.warning("No previous results found in %s", RES_LOG_DIR)
        return {}
    logger.info("Using offline cached results: %s", latest)
    try:
        with open(latest, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.exception("Failed to load cached results: %s", str(e))
        return {}


if __name__ == "__main__":
    logger.info("%s", "=" * 60)
    logger.info("Multi-agent demo started (OFFLINE_TEST=%s)", str(OFFLINE_TEST))
    logger.info("Run log: %s", _run_log_file)
    logger.info("Result file (to be written): %s", _res_json_file)
    logger.info("%s", "=" * 60)

    # 示例输入，可替换为真实输入
    user_input = (
        "{\n"
        "  \"Restaurant Type\": \"Restaurant\",\n"
        "  \"Flavor Profile\": \"Spicy\",\n"
        "  \"Dining Purpose\": \"Friends\",\n"
        "  \"Budget Range (per person)\": \"20 to 60 (SGD)\",\n"
        "  \"Location (Singapore)\": \"Chinatown\",\n"
        "  \"Food Type\": \"Sichuan food\"\n"
        "}"
    )

    # 数据容器
    plan_calls: List[Dict[str, Any]] = []
    executions: List[Dict[str, Any]] = []

    if OFFLINE_TEST:
        # 离线模式: 读取最近结果并复用工具结果
        cached = load_latest_results()
        cached_user_input = cached.get("user_input")
        if cached_user_input:
            user_input = cached_user_input
        plan_calls = cached.get("plan_calls", [])
        executions = cached.get("executions", [])
        logger.info("Offline mode: loaded %d plan_calls and %d executions", len(plan_calls), len(executions))
    else:
        logger.info("User input: %s", user_input)
        # 1) 调用规划 Agent
        logger.info("Calling planning agent...")
        planning_resp = run_demo(user_input)
        logger.info("Planning agent responded.")

        # 2) 解析工具调用计划
        plan_calls = parse_planner_output(planning_resp)
        logger.info("Parsed %d planned calls", len(plan_calls))

        # 3) 顺序执行各个工具并收集结果
        for idx, call in enumerate(plan_calls, start=1):
            name = call.get("name")
            params = call.get("parameters", {})
            logger.info("Executing plan #%d: %s", idx, name)
            exec_result = dispatch_tool_call(name, params)
            executions.append(exec_result)
            logger.info("Execution #%d finished: success=%s", idx, exec_result.get("success"))

    # 汇总阶段：抽取各工具输出并调用 agent_summary
    gmap_results = None
    xhs_results = None
    for item in executions:
        if item.get("tool") == "gmap.search":
            gmap_results = item.get("output")
        if item.get("tool") == "xhs.search":
            xhs_results = item.get("output")

    logger.info("Calling agent_summary for final recommendations...")
    summary_resp = summarize_recommendations(user_input, gmap_results, xhs_results)
    summary_content = summary_resp.choices[0].message.content if summary_resp and summary_resp.choices else None
    logger.info("agent_summary returned (%d chars)", len(summary_content) if summary_content else 0)

    # 控制台输出
    print("=== OFFLINE_TEST ===", OFFLINE_TEST)
    print("=== Planning Calls ===")
    print(json.dumps(plan_calls, ensure_ascii=False, indent=2))
    print("\n=== Executions ===")
    print(json.dumps(executions, ensure_ascii=False, indent=2))
    print("\n=== Final Summary (JSON) ===")
    print(summary_content if summary_content else "<empty>")

    # 持久化最终结果到 JSON 文件（加入 user_input 与 summary 字段）
    final_payload: Dict[str, Any] = {
        "user_input": user_input,
        "plan_calls": plan_calls,
        "executions": executions,
        "summary": None,
        "offline": OFFLINE_TEST
    }
    try:
        parsed_summary = None
        if summary_content:
            try:
                parsed_summary = json.loads(summary_content)
            except Exception:
                parsed_summary = None
        final_payload["summary"] = parsed_summary if parsed_summary is not None else summary_content

        with open(_res_json_file, "w", encoding="utf-8") as f:
            json.dump(final_payload, f, ensure_ascii=False, indent=2)
        logger.info("Final results written to: %s", _res_json_file)
    except Exception as e:
        logger.exception("Failed to write results JSON: %s", str(e))

    logger.info("%s", "=" * 60)
    logger.info("Multi-agent demo finished")
    logger.info("Run log: %s", _run_log_file)
    logger.info("Result file: %s", _res_json_file)
    logger.info("%s", "=" * 60)
