from typing import Literal
from langchain_core.runnables.graph import CurveStyle
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import AIMessage, HumanMessage, ChatMessage

import uuid
import json

from metarec.agent.state import AgentState
from metarec.agent.nodes import init_node, input_node
import metarec.agent.nodes.utils as node_utils
import metarec.agent.nodes.analysis as analysis
import metarec.agent.nodes.feedback as feedback
import metarec.agent.nodes.recommendation as recommendation

def placeholder_generate(state: AgentState, config, runtime):
    last_message = state.history[-1].content
    additional_kwargs = {}
    msg_id = str(uuid.uuid4())
    
    update = {}

    if 'MOCK:yes_no' in last_message:
        update['interactions'] = {
            msg_id: {
                'status': 'pending',
                'type': 'yes_no',
                'data': {
                    'yes_label': 'Confirm',
                    'no_label': 'Not Satisfied',
                    'yes_message': 'Yes, that is correct.',
                    'no_message': 'No, that is not quite right',
                    'dismiss_message': '[Prompt Dismissed]'
                }
            }
        }
        text = 'confirm prompt message placeholder'
    elif 'MOCK:preferences' in last_message:
        update['interactions'] = {
            msg_id: {
                'status': 'pending',
                'type': 'preferences',
                'data': {
                    'confirm_message': '[Preferences Updated]',
                    'confirm_label': 'Confirm Restaurant Preferences',
                    'preferences': recommendation.PLIST
                }
            }
        }
        text = 'preference form message placeholder'
    elif 'MOCK:restaurants' in  last_message:
        update['interactions'] = {
            msg_id: {
                'status': 'static',
                'type': 'restaurants',
                'data': {
                    'restaurants': []
                }
            }
        }
        text = 'Restaurant list message placeholder'
    elif 'MOCK:task' in  last_message:
        task_id = 'mock_task_' + str(uuid.uuid4())
        update['interactions'] = {
            msg_id: {
                'status': 'static',
                'type': 'task',
                'data': {
                    'taskId': task_id,
                }
            }
        }
        update['tasks'] = {
            task_id: {
                'task_id': task_id,
                'status': 'processing',
                'progress': 30,
                'message': 'placeholder status',
            }
        }
        text = 'Task message placeholder'
    else:
        text = f'placeholder response to last message: {last_message}'

    msg = AIMessage(id=msg_id, content=text, additional_kwargs=additional_kwargs)
    update['history'] = [msg]
    
    return update

def create_graph():
    
    memory = MemorySaver()
    graph = StateGraph(AgentState)
    graph.add_node('greetings', init_node)
    graph.add_node('on_input', input_node)
    graph.add_node('handle_interaction', feedback.handle_interaction)
    graph.add_node('detect_intent', analysis.detect_intent)
    graph.add_node('generate_rec_response', placeholder_generate)
    graph.add_edge('generate_rec_response', 'on_input')
    
    graph.add_edge(START, 'greetings')
    graph.add_edge('greetings', 'on_input')
    graph.add_conditional_edges('on_input', lambda state: state.decision, {
        'human_message': 'detect_intent',
        'interaction': 'handle_interaction'
    })
    graph.add_conditional_edges('detect_intent', lambda state: state.decision, {
        'rec': 'generate_rec_response'
    })
    
    workflow = graph.compile(
        checkpointer=memory,
        interrupt_before=['on_input'],
    )
    return workflow


if __name__ == '__main__':
    main()
