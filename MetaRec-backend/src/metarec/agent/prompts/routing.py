from metarec.agent.prompts.templating import make_template

def get_intent_detection_prompt(
    query: str,
    language: str = 'en',
):
    template_str = """You are an expert at classifying user intent.

You are to classify the users intent into one of the following categories, responding with only the category name:
    - `query`: The user is searching for something, or seeking a recommendation.
    - `chat`: The user is making general conversation or greeting.
    
User query:
{{query}}
"""
    template = make_template(template_str)
    formatted = template.render(
        query=query
    )
    return formatted
    
