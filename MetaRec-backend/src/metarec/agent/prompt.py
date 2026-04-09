def get_intent_detection_prompt(
    language: str = 'en'
):
    return """You are an expert at classifying user intent.

You are to classify the users intent into one of the following categories, responding with only the category name:
    - `query`: The user is searching for something, or seeking a recommendation.
    - `chat`: The user is making general conversation or greeting.
"""
