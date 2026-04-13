from __future__ import annotations

import tempfile
from typing import Any, Callable, Dict

from pydantic import BaseModel

from conversation_storage import ConversationStorage

# Debug unit registration lives here so collaborators have a single place to add new units
# 我把注册新单元测试的逻辑放在这儿了，各位可以在这里面新增，方便大家集中管理和维护

class UnitSpec(BaseModel):
    name: str
    description: str
    function_name: str
    input_schema: Dict[str, Any]
    expected_io: Dict[str, Any]
    sample_input: Dict[str, Any]


def _conversation_sandbox_lifecycle(payload: Dict[str, Any]) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="metarec_debug_conv_") as tmpdir:
        storage = ConversationStorage(storage_dir=tmpdir)
        user_id = payload.get("user_id", "unit_user")
        conv = storage.create_conversation(
            user_id=user_id,
            title=payload.get("title", "Debug Sandbox"),
            model="DebugUnit",
        )
        storage.add_message(user_id, conv["id"], "user", payload.get("message", "Hello"))
        if payload.get("preferences"):
            storage.update_conversation_preferences(user_id, conv["id"], payload["preferences"])
        return {
            "conversation_id": conv["id"],
            "conversation": storage.get_full_conversation(user_id, conv["id"]),
        }


# ======================= Register debug units below =======================

def register_default_debug_units(registry: Any, service_getter: Callable[[], Any]) -> None:
    register = registry.register

    register(
        UnitSpec(
            name="metarec.analyze_user_intent",
            description="Rule-based fallback intent classifier for confirmation/new query.",
            function_name="MetaRecService.analyze_user_intent",
            input_schema={"type": "object", "required": ["query"], "properties": {"query": {"type": "string", "minLength": 1}}},
            expected_io={"output_type": "object", "notes": "Returns type/confidence/original_query"},
            sample_input={"query": "I want spicy Sichuan in Chinatown"},
        ),
        lambda p: service_getter().analyze_user_intent(p["query"]),
    )

    register(
        UnitSpec(
            name="metarec.extract_preferences_from_query",
            description="Rule-based preference extraction used as fallback and baseline behavior parser.",
            function_name="MetaRecService.extract_preferences_from_query",
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "user_id": {"type": "string"},
                    "session_id": {"type": "string"},
                },
            },
            expected_io={"output_type": "object", "notes": "Preferences dict"},
            sample_input={"query": "spicy Sichuan for friends around Chinatown budget 20 to 60"},
        ),
        lambda p: service_getter().extract_preferences_from_query(
            p["query"], p.get("user_id", "debug_unit"), p.get("session_id", "debug_unit_session")
        ),
    )

    register(
        UnitSpec(
            name="metarec.preferences_to_agent_input",
            description="Converts query + preferences into planner JSON text.",
            function_name="MetaRecService._preferences_to_agent_input",
            input_schema={
                "type": "object",
                "required": ["query", "preferences"],
                "properties": {"query": {"type": "string"}, "preferences": {"type": "object"}},
            },
            expected_io={"output_type": "string", "notes": "JSON string for planner"},
            sample_input={
                "query": "Find spicy Sichuan for friends in Chinatown",
                "preferences": {
                    "restaurant_types": ["casual"],
                    "flavor_profiles": ["spicy"],
                    "dining_purpose": "friends",
                    "budget_range": {"min": 20, "max": 60, "currency": "SGD", "per": "person"},
                    "location": "Chinatown",
                },
            },
        ),
        lambda p: service_getter()._preferences_to_agent_input(p.get("query", ""), p["preferences"]),
    )

    register(
        UnitSpec(
            name="metarec.extract_restaurants_from_execution_data",
            description="Parses summary + executions into frontend restaurant objects.",
            function_name="MetaRecService._extract_restaurants_from_execution_data",
            input_schema={"type": "object", "required": ["execution_data"], "properties": {"execution_data": {"type": "object"}}},
            expected_io={"output_type": "array", "notes": "Restaurant dicts merged from summary and Google Maps"},
            sample_input={
                "execution_data": {
                    "summary": {
                        "recommendations": [
                            {
                                "name": "Test Sichuan House",
                                "area": "Chinatown",
                                "cuisine": "Sichuan",
                                "price_per_person_sgd": "20-35",
                                "why": "Fits spicy budget",
                                "sources": {"xiaohongshu": "note_1"},
                            }
                        ]
                    },
                    "executions": [
                        {
                            "tool": "gmap.search",
                            "success": True,
                            "output": [
                                {
                                    "title": "Test Sichuan House Singapore",
                                    "rating": 4.3,
                                    "reviews": 231,
                                    "price": "$$",
                                    "address": "72 Pagoda St",
                                    "gps_coordinates": {"latitude": 1.28, "longitude": 103.84},
                                    "open_state": "Open now",
                                }
                            ],
                        }
                    ],
                }
            },
        ),
        lambda p: service_getter()._extract_restaurants_from_execution_data(p["execution_data"]),
    )

    register(
        UnitSpec(
            name="conversation_storage.sandbox_lifecycle",
            description="Temp-dir conversation CRUD sandbox (isolated from production conversation files).",
            function_name="ConversationStorage lifecycle",
            input_schema={
                "type": "object",
                "required": ["user_id", "message"],
                "properties": {
                    "user_id": {"type": "string"},
                    "message": {"type": "string"},
                    "title": {"type": "string"},
                    "preferences": {"type": "object"},
                },
            },
            expected_io={"output_type": "object", "notes": "Returns final conversation snapshot"},
            sample_input={
                "user_id": "unit_user",
                "message": "I want spicy food",
                "title": "Debug Sandbox",
                "preferences": {"flavor_profiles": ["spicy"], "location": "Chinatown"},
            },
        ),
        _conversation_sandbox_lifecycle,
    )
