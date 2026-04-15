from ..state import AgentState
import uuid
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI
from langchain_core.utils.json import parse_json_markdown

async def detect_domain(state: AgentState, config, runtime):
    """
    Determines the domain in which to search for recommendations.
    """
    
    domain = 'restaurant'
    mcp_client = runtime.context.get('mcp_client', None)
    async with mcp_client:
        required_preferences = await mcp_client.call_tool(
            "private.get_domain_preferences",
            arguments={
                "domain": domain,
            }
        )
        required_preferences = required_preferences.content[0].text
        required_preferences = parse_json_markdown(required_preferences)

    return {
        'domain': 'restaurant',
        'required_preferences': required_preferences,
    }

async def detect_preferences(state: AgentState, config, runtime):
    """
    Determines the user's search preferences based on:
    - existing preferences
    - filter form values ?
    - last message input ?
    """
    use_llm = config['configurable'].get('use_llm', False)

    mcp_client = runtime.context.get('mcp_client', None)
    llm_client = runtime.context.get('llm_client', None)
    llm_model = 'gemini-3.1-flash-lite-preview'
    
    # existing preferences
    last_message = state.get('history')[-1]
    domain = state.get('domain')

    if use_llm:
        async with mcp_client:
            preference_detection_prompt = await mcp_client.get_prompt(
                "private.preference_detection",
                arguments={
                    "domain": domain,
                    "language": "en",
                    "query": last_message.content,
                }
            )
            preference_detection_prompt = preference_detection_prompt.messages[0].content.text
        
        messages = [
            {'role': 'user', 'content': preference_detection_prompt},
        ]
        response = await llm_client.chat.completions.create(
            model=llm_model,
            messages=messages,
            temperature=0.7,
            #response_format={"type": "json_object"},
        )
        output = response.choices[0].message.content
        extracted_preferences = parse_json_markdown(output)
    else:
        extracted_preferences = {}
    
    return {
        'preferences': extracted_preferences,
    }
    

def check_missing_preferences(state: AgentState, config):
    """
    Checks for missing user preferences.
    """
    required = state.get('required_preferences', [])
    existing_preferences = state.get('preferences', [])
    missing = [key for key in required if key not in existing_preferences]

    decision = 'incomplete' if len(missing) > 0 else 'complete'
    return {
        'missing_preferences': missing,
        'decision': [decision],
    }

async def prompt_for_missing_preferences(state: AgentState, config, runtime):
    """
    1. Based on a list of missing preferences, ask the LLM for a natural language message to prompt the user for missing information
    2. Adds to the message history
    """
    use_llm = config['configurable'].get('use_llm', False)

    mcp_client = runtime.context.get('mcp_client')
    llm_client = runtime.context.get('llm_client')
    llm_model = 'gemini-3.1-flash-lite-preview'

    domain = state.get('domain')
    missing = state.get('missing_preferences', [])

    if use_llm:
        async with mcp_client:
            guidance_prompt = await mcp_client.get_prompt(
                "private.missing_preferences",
                arguments = {
                    "domain": domain,
                    "missing_preferences": missing,
                }
            )
            guidance_prompt = guidance_prompt.messages[0].content.text
            messages = [{
                'role': 'user', 'content': guidance_prompt,
            }]

            response = await llm_client.chat.completions.create(
                model=llm_model,
                messages=messages,
                temperature=0.8,
                max_tokens=200,
            )
            output = response.choices[0].message.content.strip()
    else:
        output = f"missing these preferences: {str(missing)}"

    return {
        'history': [
            AIMessage(content=output),
        ]
    }

def prompt_for_preferences_confirmation(state: AgentState, config):
    """
    Prompts the user for to confirm/negate detected preferences
    """
    return {
        'history': [
            AIMessage(content="<Preferences>\nIs this correct?"),
        ]
    }

def execute_tool(state: AgentState, config):
    """
    Returns result from a tool call
    """

    task = state.get('tool_queue')[0]
    task_id = task.get('tool_call_id')
    
    result = 'placeholder'
    
    return {
        'tool_plan': {
            task_id: {
                'result': result,
            },
        },
        'tool_queue': [
            {'tool_call_id': task_id, '_action': 'pop'}
        ]
    }

def tool_planner(state: AgentState, config):
    """
    Determines tool to be called.
    """
    plan = state.get('tool_plan', {})
    queue = state.get('tool_queue', [])

    if len(plan.items()) == 0:
        call1 = {
            'tool_call_id': str(uuid.uuid4()),
            'name': 'search.books'
        }
        call2 = {
            'tool_call_id': str(uuid.uuid4()),
            'name': 'search.restaurants.yelp'
        }
        new_plan = {}
        new_plan[call1.get('tool_call_id')] = call1
        new_plan[call2.get('tool_call_id')] = call2

        return {
            'tool_plan': new_plan,
            'tool_queue': [call1, call2],
            'decision': ['execute_tool'],
        }
    elif len(queue) > 0:
        name = queue[0].get('name')
        return {
            'decision': ['execute_tool'],
        }
    else:
        return {
            'decision': ['complete'],
        }

def rank_and_filter(state: AgentState, config):
    """
    1. Accumulates search result of tool_calls.
    2. Rank and filter results (TODO)
    """
    results = []
    plan = state.get('tool_plan', {})
    for key, val in plan.items():
        result = val.get('result')
        if result is not None:
            results.append(result)

    return {
        'search_results': results
    }

def summarize(state: AgentState, config):
    """
    Summarize search results
    """
    summary_msg = 'Here are your recommendations:\nPlaceholder'
    return {
        'history': [
            AIMessage(content=summary_msg)
        ]
    }

