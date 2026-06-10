import importlib
import os

import pytest


@pytest.mark.backend_unit
def test_openapi_contract_contains_core_request_response_shapes():
    os.environ.setdefault("LLM_API_KEY", "dummy-key")
    os.environ.setdefault("OPENAI_API_KEY", "dummy-key")

    main = importlib.import_module("main")
    spec = main.app.openapi()

    assert "/api/process" in spec["paths"]
    assert "/api/status/{task_id}" in spec["paths"]

    schemas = spec["components"]["schemas"]
    assert "ProcessRequestAPI" in schemas
    assert "RecommendationResponseAPI" in schemas
    assert "TaskStatusAPI" in schemas
    assert "ConversationData" in schemas
    assert "GenericSuccessResponseAPI" in schemas
    response_props = schemas["RecommendationResponseAPI"]["properties"]
    assert "task_id" in response_props
    assert "result_id" in response_props

    process_post = spec["paths"]["/api/process"]["post"]
    request_ref = process_post["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    response_ref = process_post["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]

    assert request_ref.endswith("/ProcessRequestAPI")
    assert response_ref.endswith("/RecommendationResponseAPI")
