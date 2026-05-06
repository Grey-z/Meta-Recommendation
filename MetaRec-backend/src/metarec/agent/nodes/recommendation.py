from ..state import AgentState
import uuid
from langchain_core.messages import AIMessage
from langchain_core.utils.json import parse_json_markdown

PLIST = [
    {
        'kind': 'SelectSpec',
        'label': 'Restaurant Type',
        'options': [
            { 'value': 'casual', 'label': 'Casual' },
            { 'value': 'fine-dining', 'label': 'Fine Dining' },
            { 'value': 'fast-casual', 'label': 'Fast Casual' },
            { 'value': 'street-food', 'label': 'Street Food' },
            { 'value': 'buffet', 'label': 'Buffet' },
            { 'value': 'cafe', 'label': 'Cafe' },
        ],
        'prefKey': 'restaurant.type',
        'allowMultiple': False,
        'allowOther': False,
    },
    {
        'kind': 'SelectSpec',
        'label': 'Dietary Restrictions',
        'options': [
            { 'value': 'halal', 'label': 'Halal' },
            { 'value': 'vegetarian', 'label': 'Vegetarian' },
            { 'value': 'vegan', 'label': 'Vegen' },
            { 'value': 'no-beef', 'label': 'No Beef' },
            { 'value': 'no-nuts', 'label': 'No Nuts' },
            { 'value': 'no-gluten', 'label': 'Gluten-Free' },
            { 'value': 'other', 'label': 'Other' },
        ],
        'prefKey': 'restaurant.restrictions',
        'allowMultiple': True,
        'allowOther': True,
    },
    {
        'kind': 'SelectSpec',
        'label': 'Flavor Profiles',
        'options': [
            { 'value': 'spicy', 'label': 'Spicy' },
            { 'value': 'savory', 'label': 'Savory' },
            { 'value': 'sweet', 'label': 'Sweet' },
            { 'value': 'sour', 'label': 'Sour' },
            { 'value': 'umami', 'label': 'Umami' },
            { 'value': 'mild', 'label': 'Mild' },
        ],
        'prefKey': 'restaurant.flavor_profile',
        'allowMultiple': True,
        'allowOther': False,
    },
    {
        'kind': 'SelectSpec',
        'label': 'Dining Purpose',
        'options': [
            { 'value': 'other', 'label': 'Other' },
            { 'value': 'any', 'label': 'Any' },
            { 'value': 'date-night', 'label': 'Date Night' },
            { 'value': 'family', 'label': 'Family' },
            { 'value': 'business', 'label': 'Business' },
            { 'value': 'solo', 'label': 'Solo' },
            { 'value': 'friends', 'label': 'Friends' },
            { 'value': 'celebration', 'label': 'Celebration' },
        ],
        'prefKey': 'restaurant.dining_purpose',
        'allowMultiple': True,
        'allowOther': False,
    },
    {
        'kind': 'SelectSpec',
        'label': 'Random',
        'options': [
            { 'value': v, 'label': v } for v in map(lambda x: str(uuid.uuid4()), range(10))
        ],
        'prefKey': 'restaurant.extra_1',
        'allowMultiple': True,
        'allowOther': False,
    },
    {
        'kind': 'RangeSpec',
        'label': 'Budget Range Per Person',
        'prefKey': 'restaurant.budget',
        'lowerLimit': { 'default': 0 },
        'upperLimit': {},
        'step': 1,
    },
    {
        'kind': 'SelectSpec',
        'label': 'Location',
        'options': [
            { 'value': 'any', 'label': 'Any' },
            { 'value': 'Orchard', 'label': 'Orchard' },
            { 'value': 'Marina Bay', 'label': 'Marina Bay' },
            { 'value': 'Chinatown', 'label': 'Chinatown' },
            { 'value': 'Bugis', 'label': 'Bugis' },
            { 'value': 'Tanjong Pagar', 'label': 'Tanjong Pagar' },
            { 'value': 'Clarke Quay', 'label': 'Clarke Quay' },
            { 'value': 'Little India', 'label': 'Little India' },
            { 'value': 'Holland Village', 'label': 'Holland Village' },
            { 'value': 'Tiong Bahru', 'label': 'Tiong Bahru' },
            { 'value': 'Katong / Joo Chiat', 'label': 'Katong / Joo Chiat' },
            { 'value': 'other', 'label': 'Other' },
        ],
        'prefKey': 'restaurant.location',
        'allowMultiple': False,
        'allowOther': True,
    },
]

async def init_rec(state: AgentState, config, runtime):
    """
    Determines the domain in which to search for recommendations.
    """
    return {
        'domain': domain,
        'preferences_required': PLIST,
    }

async def detect_preferences(state: AgentState, config, runtime):
    """
    TODO: Extract preferences from conversation / last message
    """
    
    preferences = []
    
    return {
        'preferences': [],
    }

async def prompt_user(state: AgentState, config, runtime):
    """
    - Prompt for missing preferences, OR
    - Prompt user to confirm preferences to proceeed with recommendation
    """
    rec_state = state.rec_state
    
    prefs = rec_state['preferences']
    prefKeys = set([ k for k,v in prefs.items() ])

    specs = rec_state['required_preferences']
    missing_specs = [ spec for spec in specs if spec.prefKey not in prefKeys ]
    
    new_message = ""
    interaction = {}
    if len(missing_specs) > 0:
        new_message = "Missing preferences"
        interaction = {
            'type': 'preferences',
            'status': 'pending',
            'data': {
                'preferences': missing_specs,
                'confirm_label': "Update Preferences"
            },
        }
        
    else:
        new_message = "Proceed with recommendation?"
        interaction = {
            'type': 'yes_no',
            'status': 'pending',
            'data': {
                'yes_label': 'Proceed',
                'yes_message': 'Yes, proceed.',
            },
        }

    msg_id = str(uuid.uuid4())
    return {
        'history': [
            AIMessage(id=msg_id, content=new_message),
        ],
        'interactions': {
            msg_id: interaction
        },
    }


def check_missing_preferences(state: AgentState, config):
    """
    Checks for missing user preferences.
    """
    required = state.required_preferences
    existing_preferences = state.preferences

    if 'restaurant.location' in existing_preferences:
        return {
            'missing_preferences': [],
            'decision': 'preference_complete',
        }
    else:
        return {
            'missing_preferences': ['restaurant.location'],
            'decision': 'preference_incomplete',
        }

    missing = [key for key in required if key not in existing_preferences]

    decision = 'preference_incomplete' if len(missing) > 0 else 'preference_complete'
    return {
        'missing_preferences': missing,
        'decision': decision,
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

    domain = state.domain
    missing = state.missing_preferences

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

    msg_id = str(uuid.uuid4())
    return {
        'history': [
            AIMessage(id=msg_id, content=output),
        ],
        'interactions': {
            msg_id: {
                'status': 'pending',
                'type': 'preference_form',
            }
        }
    }

def prompt_for_preferences_confirmation(state: AgentState, config):
    """
    Prompts the user for to confirm/negate detected preferences
    """
    msg_id = str(uuid.uuid4())
    return {
        'history': [
            AIMessage(id=msg_id, content="<Preferences>\nIs this correct?"),
        ],
        'interactions': {
            msg_id: {
                'status': 'pending',
                'type': 'yes_no',
            }
        }
    }

def execute_tool(state: AgentState, config):
    """
    Returns result from a tool call
    """

    task = state.tool_queue[0]
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
    plan = state.tool_plan
    queue = state.tool_queue

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
            'decision': 'execute_tool',
        }
    elif len(queue) > 0:
        name = queue[0].get('name')
        return {
            'decision': 'execute_tool',
        }
    else:
        return {
            'decision': 'search_complete',
        }

def rank_and_filter(state: AgentState, config):
    """
    1. Accumulates search result of tool_calls.
    2. Rank and filter results (TODO)
    """
    results = []
    plan = state.tool_plan
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
    msg_id = str(uuid.uuid4())
    return {
        'history': [
            AIMessage(id=msg_id, content=summary_msg)
        ]
    }

