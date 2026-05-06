from ..state import AgentState
from .utils import graph_node
import re

@graph_node(name='analysis.detect_language')
def detect_language(state: AgentState, config):
    """
    Determines the language the user is using.
    Return the corresponding language code, defaulting to 'en'
    """

    last_message = state.history[-1]
    text = last_message.content
    
    chinese_pattern = re.compile(r'[\u4e00-\u9fff]')
    if chinese_pattern.search(text):
        language = "zh"
    else:
        language = 'en'
    
    return {
        'language': language,
    }

@graph_node(name='analysis.detect_intent')
async def detect_intent(state: AgentState, config, runtime):
    """
    Classifies the user's intent based on the latest `user` message.
    - "query": the user is searching for something, seeking a recommendation
    - "chat": general conversation / chat
    """
    use_llm = config['configurable'].get('use_llm', False)
    mcp_client = runtime.context.get('mcp_client')
    llm_client = runtime.context.get('llm_client')
    llm_model = 'gemini-3.1-flash-lite-preview'

    language = state.language
    last_message = state.history[-1]
    user_query = last_message.content
    
    if use_llm:
        async with mcp_client:
            prompt = await mcp_client.get_prompt(
                'private.detect_intent',
                arguments={
                    'query': user_query,
                    'language': language,
                }
            )
            prompt = prompt.messages[0].content.text
        
        messages = [
            {'role': 'user', 'content': prompt}
        ]
        response = await llm_client.chat.completions.create(
            messages=messages,
            model=llm_model,
            temperature=0.5,
            max_tokens=5,
        )
        intent = response.choices[0].message.content
    else:
        intent = 'rec'

    return {
        'decision': intent,
    }

