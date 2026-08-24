from types import SimpleNamespace

import pytest

from langgraph_metarec.json_parsing import loads_first_json_array, loads_first_json_object
from langgraph_metarec.legacy_adapters.agent import parse_planner_output
from service import _loads_llm_json

pytestmark = pytest.mark.backend_unit


def test_json_parser_uses_first_complete_typed_value_without_greedy_span():
    text = 'prefix {"recommendations": []} note {"ignored": true}'
    assert loads_first_json_object(text) == {"recommendations": []}
    assert _loads_llm_json(text) == {"recommendations": []}


def test_json_parser_prefers_expected_type_and_supports_fences():
    text = 'metadata {"kind": "note"}\n```json\n[{"name":"gmap.search","parameters":{}}]\n```'
    assert loads_first_json_array(text) == [{"name": "gmap.search", "parameters": {}}]
    with pytest.raises(ValueError):
        loads_first_json_object("plain text only")


def test_planner_parser_rejects_invalid_array_records():
    content = (
        '[{"name":"gmap.search","parameters":{"query":"Sentosa"}},'
        '{"name":"bad","parameters":[]},{"parameters":{}}]'
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))]
    )
    assert parse_planner_output(response) == [
        {"name": "gmap.search", "parameters": {"query": "Sentosa"}}
    ]
