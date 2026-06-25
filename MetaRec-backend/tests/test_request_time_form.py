import pytest

from langgraph_metarec.graphs.request_orchestrator import (
    _attach_preference_form,
    _multi_domain_confirmation,
)


@pytest.mark.backend_unit
def test_attach_preference_form_adds_request_time_movie_form():
    confirmation = {"message": "ok?", "preferences": {}, "needs_confirmation": True}
    _attach_preference_form(confirmation, "movie", {})
    form = confirmation.get("preference_form")
    assert form is not None
    assert form["domain"] == "movie"
    # genres is required and still missing -> the form asks for it.
    assert "genres" in form["missing_required"]
    genres = next(field for field in form["fields"] if field["key"] == "genres")
    assert "science fiction" in genres["options"]


@pytest.mark.backend_unit
def test_attach_preference_form_complete_when_prefs_present():
    confirmation = {"message": "ok?", "preferences": {}, "needs_confirmation": True}
    _attach_preference_form(confirmation, "movie", {"genres": ["science fiction"]})
    assert confirmation["preference_form"]["missing_required"] == []


@pytest.mark.backend_unit
def test_multi_domain_confirmation_has_no_form():
    route = {
        "domain": "multi_domain",
        "mode": "multi_domain",
        "domain_tasks": [{"domain": "movie", "status": "ready"}],
    }
    confirmation = _multi_domain_confirmation("a movie and a book", route, {})
    assert confirmation.get("preference_form") is None
    assert "multi-domain" in confirmation["message"]
