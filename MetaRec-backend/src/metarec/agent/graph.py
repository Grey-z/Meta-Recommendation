from typing import Literal
from langchain_core.runnables.graph import CurveStyle
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

# for visualizing graph
from PIL import Image

# for running?
import asyncio
import uuid
import json

from metarec.agent.state import AgentState
import metarec.agent.nodes.utils as node_utils
import metarec.agent.nodes.analysis as analysis
import metarec.agent.nodes.routing as routing
import metarec.agent.nodes.feedback as feedback
import metarec.agent.nodes.recommendation as recommendation

from metarec.agent.mcp_server import mcp as mcp_server
from metarec.llm_client import create_async_client
from fastmcp import Client as MCPClient

def create_graph(memory, tools):
    graph = StateGraph(AgentState)
    
    # localization
    graph.add_node('analysis.detect_language', analysis.detect_language)
    
    graph.add_node('analysis.detect_intent', analysis.detect_intent)

    graph.add_node('router', routing.intent_router)

    graph.add_node('conversation', node_utils.no_op)

    # determine what domains to recommend for
    graph.add_node('recommendation.detect_domain', recommendation.detect_domain)
    
    # determine arguments for search tools
    graph.add_node('recommendation.detect_preferences', recommendation.detect_preferences)

    # check if there are missing arugments
    graph.add_node('recommendation.check_preferences', recommendation.check_missing_preferences)

    # human-in-loop: prompt for confirmation of preferences before proceeding
    graph.add_node(
        'recommendation.prompt_for_preferences_confirmation', 
        recommendation.prompt_for_preferences_confirmation,
    )

    # human-in-loop: prompt for missing preferences
    graph.add_node(
        'recommendation.prompt_for_missing_preferences', 
        recommendation.prompt_for_missing_preferences,
    )

    graph.add_node(
        'recommendation.preferences_confirmation_button_press',
        feedback.button_press,
    )
    
    # generates tool call plan based on preferences
    graph.add_node('recommendation.tool_planner', recommendation.tool_planner)

    graph.add_node('recommendation.execute_tool', recommendation.execute_tool)
    
    # post processing of search results
    graph.add_node('recommendation.rank_and_filter', recommendation.rank_and_filter)
    
    # generates HTML for displaying results
    graph.add_node('recommendation.summarize', recommendation.summarize)
    
    # edges

    graph.add_edge(START, 'analysis.detect_language')
    graph.add_edge('analysis.detect_language', 'analysis.detect_intent')
    graph.add_edge('analysis.detect_intent', 'router')

    graph.add_conditional_edges('router', routing.route_decision, {
        'chat': 'conversation',
        'query_with_forced_domain': 'recommendation.detect_preferences',
        'query': 'recommendation.detect_domain',
    })
    
    #graph.add_edge('recommendation', 'recommendation.detect_domain')
    graph.add_edge('recommendation.detect_domain', 'recommendation.detect_preferences')
    graph.add_edge('recommendation.detect_preferences', 'recommendation.check_preferences')
    graph.add_conditional_edges('recommendation.check_preferences', routing.route_decision, {
        'complete': 'recommendation.prompt_for_preferences_confirmation',
        'incomplete': 'recommendation.prompt_for_missing_preferences',
    })

    graph.add_edge(
        'recommendation.prompt_for_missing_preferences', 
        'recommendation.detect_preferences'
    )

    graph.add_edge(
        'recommendation.prompt_for_preferences_confirmation',
        'recommendation.preferences_confirmation_button_press'
    )
    
    graph.add_conditional_edges(
        'recommendation.preferences_confirmation_button_press',
        routing.route_decision, {
            'yes': 'recommendation.tool_planner',
            'no': END,
        }
    )

    graph.add_edge('recommendation.rank_and_filter', 'recommendation.summarize')
    graph.add_edge('recommendation.summarize', END)
    
    graph.add_edge('recommendation.execute_tool', 'recommendation.tool_planner')
    
    graph.add_conditional_edges(
        'recommendation.tool_planner',
        routing.route_decision,
        {
            'complete': 'recommendation.rank_and_filter',
            'execute_tool': 'recommendation.execute_tool',
        }
    )
                                   
    workflow = graph.compile(
        checkpointer=memory,
        interrupt_after=[
            'recommendation.prompt_for_missing_preferences',
            'recommendation.prompt_for_preferences_confirmation',
        ]
    )
    
    return workflow

def log_event(event):
    event_type, event = event
    if event_type == 'updates':
        node_name, state_update = list(event.items())[0]
        print(f'NODE({node_name})\n{state_update}\n')
    else:
        print(event)

async def simulate_chat_loop(app):
    stream_mode = [
        'updates',
        #'values',
        #'debug',
    ]

    mcp_client = MCPClient(mcp_server)
    llm_client = create_async_client()
    
    config = {
        'configurable': {
            'thread_id': str(uuid.uuid4()),
            'use_llm': False,
        }
    }
    runtime_context = {
        'model': "AAA",
        'mcp_client': mcp_client,
        'llm_client': llm_client,
    }

    msg = 'I want to eat food'
    inputs = {
        'history': [
            HumanMessage(content=msg),
        ]
    }
    # initial query, missing info
    async for event in app.astream(inputs, config, context=runtime_context, stream_mode=stream_mode):
        log_event(event)
    
    # add missing info
    msg = 'I want to eat sichuan food near clark quay, between $10 - $30 per person, for a birthday celebration'
    inputs = {
        'history': [
            HumanMessage(content=msg),
        ]
    }
    await app.aupdate_state(
        config,
        inputs,
        as_node="recommendation.prompt_for_missing_preferences",
    )
    async for event in app.astream(None, config, context=runtime_context, stream_mode=stream_mode):
        log_event(event)

    # press yes
    msg = 'confirmation_button__press'
    inputs = {
        'history': [
            HumanMessage(content=msg),
        ]
    }
    await app.aupdate_state(
        config,
        inputs,
        as_node="recommendation.prompt_for_preferences_confirmation",
    )
    async for event in app.astream(None, config, context=runtime_context, stream_mode=stream_mode):
        log_event(event)

    return

def main():
    memory = MemorySaver()
    tools = [
        {'name': 'search.restaurants.google_maps'},
        {'name': 'search.restaurants.yelp'},
        {'name': 'search.books'},
    ]
    app = create_graph(memory, tools)
    
    path = 'viz.png'
    graph = app.get_graph()
    engine = 'graphviz'
    if engine == 'graphviz':
        png_data = graph.draw_png()
        with open(path, 'wb') as f:
            f.write(png_data)
    elif engine == 'mermaid':
        graph.draw_mermaid_png(output_file_path=path, curve_style=CurveStyle.BASIS)
    img = Image.open(path)
    #img.show()

    asyncio.run(simulate_chat_loop(app))

if __name__ == '__main__':
    main()
