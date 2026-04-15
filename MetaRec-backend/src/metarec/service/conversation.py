from typing import Optional
from fastmcp import Client as MCPClient
from langchain_core.messages import HumanMessage
from metarec.agent.graph import create_graph
from metarec.llm_client import create_async_client
from metarec.agent.mcp_server import mcp as mcp_server
from metarec.service.models import MessageData

class ConversationService:
    def __init__(self):
        self.graph = create_graph()
        self.context = {
            'mcp_client': MCPClient(mcp_server),
            'llm_client': create_async_client,
        }
    
    async def get_state(self, conversation_id):
        config = {
            'configurable': {
                'thread_id': conversation_id,
            }
        }
        result = await self.graph.aget_state(config)
        return result.values
    
    async def init(self, conversation_id, init_state = {}):
        config = {
            'configurable': {
                'thread_id': conversation_id,
            }
        }
        state = await self.graph.ainvoke(init_state, config, context=self.context)
        return conversation_id
    
    async def update_state(self, conversation_id, updates):
        config = {
            'configurable': {
                'thread_id': conversation_id,
            }
        }
        state = await self.graph.aget_state(config)
        await self.graph.aupdate_state(
            config,
            updates,
            as_node=None,
        )
    
    async def get_preferences(self, conversation_id):
        state = await self.get_state(conversation_id)
        return state.get('preferences', {})
    
    async def update_preferences(self, conversation_id, updates):
        await self.update_state(conversation_id, {
            'preferences': updates,
        })

    async def get_history(self, conversation_id):
        state = await self.get_state(conversation_id)
        history = state.get('history', [])
        history = list(map(lambda x: x.content, history))
        return history

    async def get_task_status(self, conversation_id, task_id):
        state = await self.get_state(conversation_id)
        tasks = state.get('tasks', {})
        return tasks.get(task_id, None)
        
    async def execute_query(
        self, 
        conversation_id: Optional[str]=None, 
        message: str="",
        use_online_agent: bool = False,
        streaming:bool = False
    ):
        config = {
            'configurable': {
                'thread_id': conversation_id,
                'use_llm': use_online_agent,
            }
        }

        inputs = {
            'history': [
                HumanMessage(content=message),
            ]
        }
        
        # check if conversation state exists and either:
        # continue an existing conversation thread, or begin a new conversation thread
        before = await self.graph.aget_state(config)
        continuation = False
        if before.values:
            continuation = True
            updates = inputs
            await self.graph.aupdate_state(
                config,
                updates,
                as_node=None,
            )
            inputs = None
        
        has_new_message = False
        stream_mode = ['messages', 'updates']
        async for mode, chunk in self.graph.astream(inputs, config, context=self.context, stream_mode=stream_mode):
            if mode == 'messages' and streaming:
                msg, metadata = chunk
                yield msg

            elif mode == 'updates' and not streaming:
                event = chunk
                for node_name, updates in event.items():
                    # check for new_message
                    if 'history' in updates:
                        has_new_message = True
            
        after = await self.graph.aget_state(config)
        if not streaming:
            yield has_new_message, after
    
