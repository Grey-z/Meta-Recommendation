import json
import logging
from datetime import datetime
import os
from typing import Any, Dict, List
import glob
from pathlib import Path

from agent_plan import run_demo
from agent_mcp.agent_google_map import search_google_maps
from agent_mcp.agent_xiaohongshu import search_notes_by_keyword
from agent_summary import summarize_recommendations


# 日志与结果目录（使用相对于当前文件的路径）
_base_dir = Path(__file__).parent
RUN_LOG_DIR = _base_dir / "demo_run_log"
RES_LOG_DIR = _base_dir / "demo_res_log"
os.makedirs(RUN_LOG_DIR, exist_ok=True)
os.makedirs(RES_LOG_DIR, exist_ok=True)

# 离线测试开关: 环境变量 OFFLINE_TEST=1 开启
OFFLINE_TEST = os.getenv("OFFLINE_TEST", "0") == "1"

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

    # 初始化阶段进度跟踪
    stage_progress = []
    
    if OFFLINE_TEST:
        # 离线模式: 读取最近结果并复用工具结果
        cached = load_latest_results()
        cached_user_input = cached.get("user_input")
        if cached_user_input:
            user_input = cached_user_input
        plan_calls = cached.get("plan_calls", [])
        executions = cached.get("executions", [])
        logger.info("Offline mode: loaded %d plan_calls and %d executions", len(plan_calls), len(executions))
        
        # 模拟规划阶段输出
        logger.info("=" * 60)
        logger.info("Stage 1/3: Planning tools...")
        logger.info("=" * 60)
        stage_progress.append({
            "stage": "planning",
            "stage_number": 1,
            "status": "started",
            "message": "Planning tools..."
        })
        
        # 提取工具名称
        tool_names = [call.get("name", "unknown") for call in plan_calls]
        tool_names_display = ", ".join([name.replace("gmap.search", "Google Maps").replace("xhs.search", "Xiaohongshu") for name in tool_names])
        logger.info("Selected tools: %s", tool_names_display if tool_names_display else "None")
        logger.info("=" * 60)
        stage_progress.append({
            "stage": "planning",
            "stage_number": 1,
            "status": "completed",
            "message": f"Selected tools: {tool_names_display if tool_names_display else 'None'}",
            "tools": tool_names
        })
        
        # 模拟工具执行阶段输出
        logger.info("Stage 2/3: Executing tools...")
        logger.info("=" * 60)
        stage_progress.append({
            "stage": "execution",
            "stage_number": 2,
            "status": "started",
            "message": "Executing tools..."
        })
        
        for idx, execution in enumerate(executions, start=1):
            tool_name = execution.get("tool", "unknown")
            tool_display = tool_name.replace("gmap.search", "Google Maps").replace("xhs.search", "Xiaohongshu")
            logger.info("  [%d/%d] Executing: %s", idx, len(executions), tool_display)
            
            # 提取 query 和 results_count
            query = execution.get("input", {}).get("query", "")
            output = execution.get("output", [])
            results_count = len(output) if isinstance(output, list) else 0
            
            stage_progress.append({
                "stage": "execution",
                "stage_number": 2,
                "status": "in_progress",
                "message": f"Executing: {tool_display}",
                "tool": tool_name,
                "progress": f"{idx}/{len(executions)}",
                "query": query,
                "results_count": results_count
            })
        
        logger.info("Tool execution completed")
        logger.info("=" * 60)
        stage_progress.append({
            "stage": "execution",
            "stage_number": 2,
            "status": "completed",
            "message": "Tool execution completed"
        })
    else:
        logger.info("User input: %s", user_input)
        
        # 1) 调用规划 Agent
        logger.info("=" * 60)
        logger.info("Stage 1/3: Planning tools...")
        logger.info("=" * 60)
        stage_progress.append({
            "stage": "planning",
            "stage_number": 1,
            "status": "started",
            "message": "Planning tools..."
        })
        
        planning_resp = run_demo(user_input)
        
        # 2) 解析工具调用计划
        plan_calls = parse_planner_output(planning_resp)
        tool_names = [call.get("name", "unknown") for call in plan_calls]
        tool_names_display = ", ".join([name.replace("gmap.search", "Google Maps").replace("xhs.search", "Xiaohongshu") for name in tool_names])
        logger.info("Selected tools: %s", tool_names_display if tool_names_display else "None")
        logger.info("=" * 60)
        stage_progress.append({
            "stage": "planning",
            "stage_number": 1,
            "status": "completed",
            "message": f"Selected tools: {tool_names_display if tool_names_display else 'None'}",
            "tools": tool_names
        })

        # 3) 顺序执行各个工具并收集结果
        logger.info("Stage 2/3: Executing tools...")
        logger.info("=" * 60)
        stage_progress.append({
            "stage": "execution",
            "stage_number": 2,
            "status": "started",
            "message": "Executing tools..."
        })
        
        for idx, call in enumerate(plan_calls, start=1):
            name = call.get("name")
            params = call.get("parameters", {})
            tool_display = name.replace("gmap.search", "Google Maps").replace("xhs.search", "Xiaohongshu")
            logger.info("  [%d/%d] Executing: %s", idx, len(plan_calls), tool_display)
            
            exec_result = dispatch_tool_call(name, params)
            executions.append(exec_result)
            
            # 提取 query 和 results_count
            query = params.get("query", "")
            output = exec_result.get("output", [])
            results_count = len(output) if isinstance(output, list) else 0
            
            stage_progress.append({
                "stage": "execution",
                "stage_number": 2,
                "status": "in_progress",
                "message": f"Executing: {tool_display}",
                "tool": name,
                "progress": f"{idx}/{len(plan_calls)}",
                "query": query,
                "results_count": results_count
            })
            
            logger.info("  [%d/%d] Completed: success=%s", idx, len(plan_calls), exec_result.get("success"))
        
        logger.info("Tool execution completed")
        logger.info("=" * 60)
        stage_progress.append({
            "stage": "execution",
            "stage_number": 2,
            "status": "completed",
            "message": "Tool execution completed"
        })

    # 汇总阶段：抽取各工具输出并调用 agent_summary
    logger.info("Stage 3/3: Generating recommendations summary...")
    logger.info("=" * 60)
    stage_progress.append({
        "stage": "summary",
        "stage_number": 3,
        "status": "started",
        "message": "Generating recommendations summary..."
    })
    
    gmap_results = None
    xhs_results = None
    for item in executions:
        if item.get("tool") == "gmap.search":
            gmap_results = item.get("output")
        if item.get("tool") == "xhs.search":
            xhs_results = item.get("output")

    summary_content = None
    if OFFLINE_TEST:
        # 离线模式：读取最新的 agent_summary 结果文件
        from pathlib import Path
        summary_log_dir = Path(__file__).parent / "agent_log" / "agent_summary"
        try:
            summary_files = sorted(
                glob.glob(str(summary_log_dir / "agent_summary_result_*.json")),
                reverse=True
            )
            if summary_files:
                latest_summary_file = summary_files[0]
                logger.info("Using cached summary: %s", os.path.basename(latest_summary_file))
                with open(latest_summary_file, "r", encoding="utf-8") as f:
                    cached_summary = json.load(f)
                    # 提取 summary 字段
                    summary_obj = cached_summary.get("summary")
                    if isinstance(summary_obj, dict):
                        summary_content = json.dumps(summary_obj, ensure_ascii=False)
                    elif isinstance(summary_obj, str):
                        summary_content = summary_obj
                    else:
                        summary_content = None
                logger.info("Loaded cached summary (%d chars)", len(summary_content) if summary_content else 0)
            else:
                logger.warning("No cached summary files found: %s", summary_log_dir)
        except Exception as e:
            logger.exception("Failed to load cached summary: %s", str(e))
    
    if not summary_content:
        # 在线模式或离线模式未找到缓存时，调用 agent_summary
        logger.info("Calling AI to generate recommendations...")
        summary_resp = summarize_recommendations(user_input, gmap_results, xhs_results)
        summary_content = summary_resp.choices[0].message.content if summary_resp and summary_resp.choices else None
        logger.info("AI summary generated (%d chars)", len(summary_content) if summary_content else 0)
    
    logger.info("Recommendations summary completed")
    logger.info("=" * 60)
    stage_progress.append({
        "stage": "summary",
        "stage_number": 3,
        "status": "completed",
        "message": "Recommendations summary completed",
        "summary_length": len(summary_content) if summary_content else 0
    })

    # 控制台输出
    print("=== OFFLINE_TEST ===", OFFLINE_TEST)
    print("=== Planning Calls ===")
    print(json.dumps(plan_calls, ensure_ascii=False, indent=2))
    print("\n=== Executions ===")
    print(json.dumps(executions, ensure_ascii=False, indent=2))
    print("\n=== Final Summary (JSON) ===")
    print(summary_content if summary_content else "<empty>")

    # 持久化最终结果到 JSON 文件（加入 user_input、summary 和 stage_progress 字段）
    final_payload: Dict[str, Any] = {
        "user_input": user_input,
        "plan_calls": plan_calls,
        "executions": executions,
        "summary": None,
        "stage_progress": stage_progress,  # 添加阶段进度跟踪
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
