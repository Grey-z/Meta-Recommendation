from metarec.agent.mcp_server import mcp as mcp_server
from fastmcp import Client
from metarec.llm_client import create_async_client
import asyncio
import json
from jinja2 import Template

template_str = """
Tool plan:
{% for tool_call in tool_calls %}
{{ tool_call.function_name}}(
    {% for k,v in tool_call.arguments.items() %}
    {{k}} = {{v}}{% if not loop.last %},{% endif %}
    {% endfor %}

)
{% endfor %}
"""
template = Template(template_str, trim_blocks=True, lstrip_blocks=True)

async def main(mcp_client, llm_client):
    llm_model = 'gemini-3.1-flash-lite-preview'

    async with mcp_client:
        available = []
        tools = await mcp_client.list_tools()
        for tool in tools:
            if tool.name.startswith('private.'):
                continue
            print('-`{name}`: {description}'.format(
                name=tool.name,
                description=tool.description
            ))
            available.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    # CRITICAL: MCP calls it 'inputSchema', OpenAI calls it 'parameters'
                    "parameters": tool.inputSchema, 
                }
            })
        
        tools = available
        messages = [
            {'role': 'system', 'content': "You are a tool call planner. Based on request, pick all the appropriate tools to call"},
            {'role': 'user', 'content': """I want to search for sichuan restaurants."""}
        ]
        
        response = await llm_client.chat.completions.create(
            model=llm_model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        tool_calls = []
        for tool_call in response.choices[0].message.tool_calls:
            fn_name = tool_call.function.name
            fn_args = json.loads(tool_call.function.arguments)
            tool_calls.append({
                'function_name': fn_name,
                'arguments': fn_args
            })
        
        formatted = template.render(
            tool_calls=tool_calls
        )

        print(formatted)
if  __name__ == '__main__':
    mcp_client = Client(mcp_server)
    llm_client = create_async_client()
    asyncio.run(main(mcp_client, llm_client))



