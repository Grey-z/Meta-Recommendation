"""
Agent 执行器模块
封装 agent 执行逻辑，支持通过 yield 返回状态更新
"""
import json
import logging
import os
import sys
import glob
from pathlib import Path
from typing import Any, Dict, List, AsyncGenerator, Optional
from .agent_plan import run_demo
from .agent_mcp.agent_google_map import search_google_maps
from .agent_mcp.agent_xiaohongshu import search_notes_by_keyword
from .agent_summary import summarize_recommendations

# 配置 logger，确保实时输出到控制台
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 如果 logger 还没有 handler，添加一个 StreamHandler
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter(
        '%(asctime)s - [%(name)s] - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False  # 防止日志向上传播，避免重复输出


# 结果目录（使用相对于当前文件的路径）
_base_dir = Path(__file__).parent
RES_LOG_DIR = _base_dir / "demo_res_log"
os.makedirs(RES_LOG_DIR, exist_ok=True)


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
    print("Planner raw content: %s", content if isinstance(content, str) else str(content))

    # 优先解析标准 tool_calls
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        print("Planner returned %d tool_calls", len(tool_calls))
        for idx, tc in enumerate(tool_calls, start=1):
            fn = tc.get("function", {}) if isinstance(tc, dict) else getattr(tc, "function", {})
            name = fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)
            arguments = fn.get("arguments") if isinstance(fn, dict) else getattr(fn, "arguments", "{}")
            try:
                params = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
            except Exception:
                params = {}
            results.append({"name": name, "parameters": params or {}})
            print("Parsed tool_call #%d -> name=%s, parameters=%s", idx, name, json.dumps(params, ensure_ascii=False))
        return results

    # 兼容内容为JSON数组的自定义格式
    if isinstance(content, str):
        text = content.strip()
        if text.startswith("[") and text.endswith("]"):
            try:
                arr = json.loads(text)
                print("Planner returned JSON array with %d items", len(arr))
                for idx, item in enumerate(arr, start=1):
                    name = item.get("function_name") or item.get("name")
                    params = item.get("parameters") or {}
                    results.append({"name": name, "parameters": params})
                    print("Parsed plan item #%d -> name=%s, parameters=%s", idx, name, json.dumps(params, ensure_ascii=False))
                return results
            except Exception as e:
                logger.warning("Failed to parse planner JSON array: %s", str(e))

    logger.warning("Planner output could not be parsed into tool calls.")
    return results


def load_latest_results() -> Dict[str, Any]:
    """
    加载最新的缓存结果
    
    Returns:
        包含 plan_calls 和 executions 的字典
    """
    files = sorted(glob.glob(os.path.join(RES_LOG_DIR, "demo_res_*.json")), reverse=True)
    latest = files[0] if files else None
    if not latest or not os.path.exists(latest):
        logger.warning("No previous results found in %s", RES_LOG_DIR)
        return {}
    print("Using offline cached results: %s", latest)
    try:
        with open(latest, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.exception("Failed to load cached results: %s", str(e))
        return {}


def dispatch_tool_call(name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    根据工具名分发到具体实现。返回 {tool: name, input: parameters, output: any, success: bool}
    """
    result: Dict[str, Any] = {"tool": name, "input": parameters, "success": False}
    print("Dispatching tool: %s with parameters: %s", name, json.dumps(parameters, ensure_ascii=False))

    try:
        if name == "gmap.search":
            query = parameters.get("query", "")
            output = search_google_maps(query=query, max_results=10)
            result.update({"output": output, "success": output is not None})
            print("gmap.search success=%s, items=%s", result["success"], len(output) if output else 0)
            return result

        if name == "xhs.search":
            query = parameters.get("query", "")
            output = search_notes_by_keyword(keyword=query, max_results=10)
            result.update({"output": output, "success": output is not None})
            print("xhs.search success=%s, items=%s", result["success"], len(output) if output else 0)
            return result

        # 未知工具
        result.update({"error": f"Unknown tool: {name}"})
        logger.warning("Unknown tool encountered: %s", name)
        return result
    except Exception as e:
        result.update({"error": str(e)})
        logger.exception("Tool execution error for %s: %s", name, str(e))
        return result


async def execute_offline_agent(user_input: str) -> AsyncGenerator[Dict[str, Any], None]:
    """
    执行 agent 管道，通过 yield 返回状态更新
    
    Args:
        user_input: 用户输入（可以是 JSON 字符串或字典）
        
    Yields:
       状态更新字典，包含：
        - stage: "planning" | "execution" | "summary"
        - stage_number: 1 | 2 | 3
        - status: "started" | "in_progress" | "completed" | "error"
        - message: 状态消息
        - progress: 进度信息（可选）
        - tool: 工具名称（可选）
        - query: 查询内容（可选）
    """
    import asyncio
    # 数据容器
    plan_calls: List[Dict[str, Any]] = []
    executions: List[Dict[str, Any]] = []
    # 离线模式: 读取最近结果并复用工具结果
    cached = load_latest_results()
    
    # 如果缓存为空，尝试加载所有缓存文件并随机选择一个
    if not cached or not cached.get("plan_calls") or not cached.get("executions"):
        try:
            all_cache_files = sorted(
                glob.glob(os.path.join(RES_LOG_DIR, "demo_res_*.json")),
                reverse=True
            )
            if all_cache_files:
                import random
                random_cache_file = random.choice(all_cache_files)
                print("Primary cache is empty, loading random cache: %s", os.path.basename(random_cache_file))
                with open(random_cache_file, "r", encoding="utf-8") as f:
                    cached = json.load(f)
            else:
                logger.warning("No cache files found in offline mode")
        except Exception as e:
            logger.exception("Failed to load random cache: %s", str(e))
    
    cached_user_input = cached.get("user_input") if cached else None
    if cached_user_input:
        user_input = cached_user_input
    plan_calls = cached.get("plan_calls", []) if cached else []
    executions = cached.get("executions", []) if cached else []
    print("Offline mode: loaded %d plan_calls and %d executions", len(plan_calls), len(executions))
    
    # 如果仍然没有数据，使用空数据但继续流程
    if not plan_calls:
        logger.warning("Offline mode: No plan_calls found, using empty list")
    if not executions:
        logger.warning("Offline mode: No executions found, using empty list")
    
    # Stage 1: Planning tools (模拟)
    yield {
        "stage": "planning",
        "stage_number": 1,
        "status": "started",
        "message": "Planning tools..."
    }
    
    # 模拟规划阶段的延迟（1-2秒）
    await asyncio.sleep(1.5)
    
    # 提取工具名称
    tool_names = [call.get("name", "unknown") for call in plan_calls]
    tool_names_display = ", ".join([
        name.replace("gmap.search", "Google Maps").replace("xhs.search", "Xiaohongshu") 
        for name in tool_names
    ])
    
    yield {
        "stage": "planning",
        "stage_number": 1,
        "status": "completed",
        "message": f"Selected tools: {tool_names_display if tool_names_display else 'None'}",
        "tools": tool_names
    }
    
    # Stage 2: Executing tools (模拟)
    yield {
        "stage": "execution",
        "stage_number": 2,
        "status": "started",
        "message": "Executing tools..."
    }
    
    # 模拟执行阶段开始前的延迟（0.5秒）
    await asyncio.sleep(0.5)
    
    for idx, execution in enumerate(executions, start=1):
        tool_name = execution.get("tool", "unknown")
        tool_display = tool_name.replace("gmap.search", "Google Maps").replace("xhs.search", "Xiaohongshu")
        
        # 提取 query 和 results_count
        query = execution.get("input", {}).get("query", "")
        output = execution.get("output", [])
        results_count = len(output) if isinstance(output, list) else 0
        
        yield {
            "stage": "execution",
            "stage_number": 2,
            "status": "in_progress",
            "message": f"Executing: {tool_display}",
            "tool": tool_name,
            "progress": f"{idx}/{len(executions)}",
            "query": query,
            "results_count": results_count
        }
        
        # 模拟每个工具执行的延迟（2-4秒，根据工具类型调整）
        if tool_name == "gmap.search":
            # Google Maps 搜索通常较快
            await asyncio.sleep(2.0)
        elif tool_name == "xhs.search":
            # 小红书搜索可能需要更长时间
            await asyncio.sleep(3.0)
        else:
            # 默认延迟
            await asyncio.sleep(2.5)
    
    yield {
        "stage": "execution",
        "stage_number": 2,
        "status": "completed",
        "message": "Tool execution completed"
    }

    
    # Stage 3: Generating recommendations summary
    yield {
        "stage": "summary",
        "stage_number": 3,
        "status": "started",
        "message": "Generating recommendations summary..."
    }
    try:
        summary_content = None

        # 离线模式：读取最新的 agent_summary 结果文件
        summary_log_dir = _base_dir / "agent_log" / "agent_summary"
        try:
            summary_files = sorted(
                glob.glob(str(summary_log_dir / "agent_summary_result_*.json")),
                reverse=True
            )
            if summary_files:
                # 优先使用最新的，如果没有找到合适的，随机选择一个
                latest_summary_file = summary_files[0]
                print("Using cached summary: %s", os.path.basename(latest_summary_file))
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
                print("Loaded cached summary (%d chars)", len(summary_content) if summary_content else 0)
                
                # 如果最新的 summary 为空或无效，尝试从其他缓存文件中随机选择一个
                if not summary_content and len(summary_files) > 1:
                    import random
                    random_file = random.choice(summary_files[1:])  # 排除已经尝试过的第一个
                    print("Latest summary is empty, trying random cached summary: %s", os.path.basename(random_file))
                    with open(random_file, "r", encoding="utf-8") as f:
                        random_cached_summary = json.load(f)
                        random_summary_obj = random_cached_summary.get("summary")
                        if isinstance(random_summary_obj, dict):
                            summary_content = json.dumps(random_summary_obj, ensure_ascii=False)
                        elif isinstance(random_summary_obj, str):
                            summary_content = random_summary_obj
                    if summary_content:
                        print("Loaded random cached summary (%d chars)", len(summary_content))
            else:
                logger.warning("No cached summary files found: %s", summary_log_dir)
                # 如果没有找到任何缓存文件，尝试从 demo_res_log 中加载
                try:
                    demo_res_files = sorted(
                        glob.glob(str(RES_LOG_DIR / "demo_res_*.json")),
                        reverse=True
                    )
                    if demo_res_files:
                        import random
                        random_demo_file = random.choice(demo_res_files)
                        print("No summary cache found, loading from demo_res_log: %s", os.path.basename(random_demo_file))
                        with open(random_demo_file, "r", encoding="utf-8") as f:
                            demo_data = json.load(f)
                            demo_summary = demo_data.get("summary")
                            if isinstance(demo_summary, dict):
                                summary_content = json.dumps(demo_summary, ensure_ascii=False)
                            elif isinstance(demo_summary, str):
                                summary_content = demo_summary
                        if summary_content:
                            print("Loaded summary from demo_res_log (%d chars)", len(summary_content))
                except Exception as e:
                    logger.exception("Failed to load summary from demo_res_log: %s", str(e))
        except Exception as e:
            logger.exception("Failed to load cached summary: %s", str(e))
        
        # 模拟加载缓存和处理的延迟（2-3秒，模拟 AI 处理时间）
        if summary_content:
            await asyncio.sleep(2.5)

        yield {
            "stage": "summary",
            "stage_number": 3,
            "status": "completed",
            "message": "Recommendations summary completed",
            "summary_length": len(summary_content) if summary_content else 0
        }

        # 最后返回完整结果
        yield {
            "stage": "completed",
            "stage_number": 3,
            "status": "completed",
            "message": "All stages completed",
            "plan_calls": plan_calls,
            "executions": executions,
            "summary": summary_content
        }
    except Exception as e:
        logger.exception("Summary stage error: %s", str(e))
        yield {
            "stage": "summary",
            "stage_number": 3,
            "status": "error",
            "message": f"Summary generation failed: {str(e)}"
        }


async def execute_online_agent(user_input: str) -> AsyncGenerator[Dict[str, Any], None]:
    """
    执行 agent 管道，通过 yield 返回状态更新
    
    Args:
        user_input: 用户输入（可以是 JSON 字符串或字典）
        
    Yields:
       状态更新字典，包含：
        - stage: "planning" | "execution" | "summary"
        - stage_number: 1 | 2 | 3
        - status: "started" | "in_progress" | "completed" | "error"
        - message: 状态消息
        - progress: 进度信息（可选）
        - tool: 工具名称（可选）
        - query: 查询内容（可选）
    """
    import asyncio

    # 数据容器
    plan_calls: List[Dict[str, Any]] = []
    executions: List[Dict[str, Any]] = []
    # 在线模式
    # Stage 1: Planning tools
    yield {
        "stage": "planning",
        "stage_number": 1,
        "status": "started",
        "message": "Planning tools..."
    }
    
    try:
        # 在线程池中执行同步的 run_demo 调用
        planning_resp = await asyncio.to_thread(run_demo, user_input)
        plan_calls = parse_planner_output(planning_resp)
        tool_names = [call.get("name", "unknown") for call in plan_calls]
        tool_names_display = ", ".join([
            name.replace("gmap.search", "Google Maps").replace("xhs.search", "Xiaohongshu") 
            for name in tool_names
        ])
        
        yield {
            "stage": "planning",
            "stage_number": 1,
            "status": "completed",
            "message": f"Selected tools: {tool_names_display if tool_names_display else 'None'}",
            "tools": tool_names
        }
    except Exception as e:
        logger.exception("Planning stage error: %s", str(e))
        yield {
            "stage": "planning",
            "stage_number": 1,
            "status": "error",
            "message": f"Planning failed: {str(e)}"
        }
        return
    
    # Stage 2: Executing tools
    yield {
        "stage": "execution",
        "stage_number": 2,
        "status": "started",
        "message": "Executing tools..."
    }
    
    for idx, call in enumerate(plan_calls, start=1):
        name = call.get("name")
        params = call.get("parameters", {})
        tool_display = name.replace("gmap.search", "Google Maps").replace("xhs.search", "Xiaohongshu")
        
        yield {
            "stage": "execution",
            "stage_number": 2,
            "status": "in_progress",
            "message": f"Executing: {tool_display}",
            "tool": name,
            "progress": f"{idx}/{len(plan_calls)}",
            "query": params.get("query", "")
        }
        
        try:
            # 在线程池中执行同步的工具调用
            exec_result = await asyncio.to_thread(dispatch_tool_call, name, params)
            executions.append(exec_result)
            
            # 提取结果数量
            output = exec_result.get("output", [])
            results_count = len(output) if isinstance(output, list) else 0
            
            yield {
                "stage": "execution",
                "stage_number": 2,
                "status": "in_progress",
                "message": f"Completed: {tool_display}",
                "tool": name,
                "progress": f"{idx}/{len(plan_calls)}",
                "query": params.get("query", ""),
                "results_count": results_count,
                "success": exec_result.get("success", False)
            }
        except Exception as e:
            logger.exception("Tool execution error: %s", str(e))
            yield {
                "stage": "execution",
                "stage_number": 2,
                "status": "error",
                "message": f"Error executing {tool_display}: {str(e)}",
                "tool": name,
                "progress": f"{idx}/{len(plan_calls)}"
            }
    
    yield {
        "stage": "execution",
        "stage_number": 2,
        "status": "completed",
        "message": "Tool execution completed"
    }
    
    # Stage 3: Generating recommendations summary
    yield {
        "stage": "summary",
        "stage_number": 3,
        "status": "started",
        "message": "Generating recommendations summary..."
    }
    try:
        # 提取各工具输出
        gmap_results = None
        xhs_results = None
        for item in executions:
            if item.get("tool") == "gmap.search":
                gmap_results = item.get("output")
            if item.get("tool") == "xhs.search":
                xhs_results = item.get("output")
        
        summary_content = None
        if not summary_content:
            # 只有在在线模式下才调用 agent_summary
            print("Calling AI to generate recommendations...")
            summary_resp = await asyncio.to_thread(
                summarize_recommendations, 
                user_input, 
                gmap_results, 
                xhs_results
            )
            summary_content = summary_resp.choices[0].message.content if summary_resp and summary_resp.choices else None
            print("AI summary generated (%d chars)", len(summary_content) if summary_content else 0)
        
        yield {
            "stage": "summary",
            "stage_number": 3,
            "status": "completed",
            "message": "Recommendations summary completed",
            "summary_length": len(summary_content) if summary_content else 0
        }
        
        # 最后返回完整结果
        yield {
            "stage": "completed",
            "stage_number": 3,
            "status": "completed",
            "message": "All stages completed",
            "plan_calls": plan_calls,
            "executions": executions,
            "summary": summary_content
        }
    except Exception as e:
        logger.exception("Summary stage error: %s", str(e))
        yield {
            "stage": "summary",
            "stage_number": 3,
            "status": "error",
            "message": f"Summary generation failed: {str(e)}"
        }


async def execute_agent_pipeline(
    user_input: str,
    use_online: Optional[bool] = None
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    执行 agent 管道，通过 yield 返回状态更新
    
    Args:
        user_input: 用户输入（可以是 JSON 字符串或字典）
        use_online: 是否使用在线模式（None 时使用环境变量 OFFLINE_TEST）
        
    Yields:
        状态更新字典，包含：
        - stage: "planning" | "execution" | "summary"
        - stage_number: 1 | 2 | 3
        - status: "started" | "in_progress" | "completed" | "error"
        - message: 状态消息
        - progress: 进度信息（可选）
        - tool: 工具名称（可选）
        - query: 查询内容（可选）
        - results_count: 结果数量（可选）
        - summary_length: 总结长度（可选）
        - tools: 工具列表（可选）
    """
    
    # 确定是否使用离线模式
    # use_online=True 表示在线模式（不使用缓存）
    # use_online=False 表示离线模式（使用缓存）
    # use_online=None 时使用环境变量
    print("Agent pipeline: use_online=%s (type: %s)", use_online, type(use_online))
    print(f"[Agent Executor] execute_agent_pipeline - use_online: {use_online} (type: {type(use_online)})")
    
    
    if use_online:
        agent_pipeline = execute_online_agent
    else:
        agent_pipeline = execute_offline_agent
    
    async for result in agent_pipeline(user_input):
        yield result

