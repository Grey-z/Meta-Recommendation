import pytest

from langgraph_metarec.graphs.request_orchestrator import _generic_confirmation


@pytest.mark.backend_unit
def test_generic_confirmation_attaches_request_time_movie_form():
    route = {"domain": "movie", "execution_domain": "movie", "status": "ready", "mode": "single_domain"}
    confirmation = _generic_confirmation("a quiet sci-fi movie", route, {})
    form = confirmation.get("preference_form")
    assert form is not None
    assert form["domain"] == "movie"
    # genres is required and still missing -> the form asks for it.
    assert "genres" in form["missing_required"]
    genres = next(field for field in form["fields"] if field["key"] == "genres")
    assert "science fiction" in genres["options"]


@pytest.mark.backend_unit
def test_generic_confirmation_form_complete_when_prefs_present():
    route = {"domain": "movie", "execution_domain": "movie", "status": "ready", "mode": "single_domain"}
    confirmation = _generic_confirmation("sci-fi", route, {"genres": ["science fiction"]})
    assert confirmation["preference_form"]["missing_required"] == []


@pytest.mark.backend_unit
def test_multi_domain_confirmation_has_no_form():
    route = {
        "domain": "multi_domain",
        "mode": "multi_domain",
        "domain_tasks": [{"domain": "movie", "status": "ready"}],
    }
    confirmation = _generic_confirmation("a movie and a book", route, {})
    assert confirmation.get("preference_form") is None
