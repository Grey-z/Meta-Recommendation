from metarec.preferences.registry import PreferenceSpec
from metarec.agent.prompts.templating import make_template

def get_missing_preferences_guidance_prompt(
    domain: str,
    missing_preferences: list[str],
):
    template_str = """You are an expert at {{ domain }} recommendations.

The user is missing the following {{ domain }} preferences:
{% for key in missing %}
    - `{{ key }}`
{% endfor %}

Generate natural friendly guidance message(2-3 sentences): no list format, natural language like chatting, friendly casual not pressuring, guide user to provide these missing preference information, can give examples, friendly encouraging tone, e.g. "To better recommend restaurants for you, could you tell me your preferred restaurant type? For example, casual dining, fine dining, etc.". Return only guidance message."""
    template = make_template(template_str)
    formatted = template.render(
        domain=domain,
        missing=missing_preferences
    )
    return formatted

def get_preference_detection_prompt(
    preference_specs: list[PreferenceSpec],
    query: str,
    domain: str,
    language: str = 'en',
):
    template_str = """You are an expert at understanding {{ domain }} preferences.

# Instructions

Extract the value from the or null for each of the following preference types.
{% for spec in preference_specs %}
    {% if spec.description %}
    - `{{ spec.key }}`: {{ spec.description }}
    {% else %}
    - `{{ spec.key }}`
    {% endif %}
{% endfor %}

Respond with JSON only

# User query
{{ query }}"""

    template = make_template(template_str)
    formatted = template.render(
        domain=domain,
        preference_specs=preference_specs,
        query=query,
    )

    return formatted
