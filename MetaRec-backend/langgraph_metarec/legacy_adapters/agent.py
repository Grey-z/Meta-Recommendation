from __future__ import annotations

import glob
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from langgraph_metarec.json_parsing import loads_first_json_array


logger = logging.getLogger(__name__)

AGENT_DIR = Path(__file__).resolve().parents[2] / "agent"
RES_LOG_DIR = AGENT_DIR / "demo_res_log"


def parse_planner_output(response: Any) -> List[Dict[str, Any]]:
    """Parse legacy planner output into graph tool-call records."""
    results: List[Dict[str, Any]] = []
    choices = getattr(response, "choices", None)
    if not choices:
        return results

    message = choices[0].message
    content = getattr(message, "content", None)

    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        for tool_call in tool_calls:
            fn = tool_call.get("function", {}) if isinstance(tool_call, dict) else getattr(tool_call, "function", {})
            name = fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)
            arguments = fn.get("arguments") if isinstance(fn, dict) else getattr(fn, "arguments", "{}")
            try:
                parameters = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
            except Exception:
                parameters = {}
            if isinstance(name, str) and name.strip() and isinstance(parameters, dict):
                results.append({"name": name.strip(), "parameters": parameters})
        return results

    if isinstance(content, str):
        try:
            items = loads_first_json_array(content)
        except (TypeError, ValueError) as exc:
            logger.warning("Failed to parse planner JSON array: %s", exc)
            return results
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("function_name") or item.get("name")
            parameters = item.get("parameters", {})
            if parameters is None:
                parameters = {}
            if isinstance(name, str) and name.strip() and isinstance(parameters, dict):
                results.append({"name": name.strip(), "parameters": parameters})
    return results


def load_latest_results() -> Dict[str, Any]:
    """Load latest offline demo result for graph offline mode."""
    files = sorted(glob.glob(str(RES_LOG_DIR / "demo_res_*.json")), reverse=True)
    latest = files[0] if files else None
    if not latest:
        logger.warning("No previous results found in %s", RES_LOG_DIR)
        return {}
    try:
        with open(latest, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception as exc:
        logger.exception("Failed to load cached results: %s", exc)
        return {}
