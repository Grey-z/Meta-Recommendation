import uuid
from typing import Optional, Dict, Any
from fastmcp import Client as MCPClient
from langchain_core.messages import HumanMessage, ChatMessage
from metarec.agent.state import AgentState
from metarec.agent.graph import create_graph
from metarec.llm_client import create_async_client
from metarec.agent.mcp_server import mcp as mcp_server
from metarec.service.models import MessageData, InteractionUpdate

class ConversationService:
    def __init__(self):
        self.graph = create_graph()
        self.context = {
            'mcp_client': MCPClient(mcp_server),
            'llm_client': create_async_client,
        }
    
    async def vizualize(self):
        g = self.graph.get_graph()
        png_data = g.draw_png()
        return png_data
    
    async def get_state(self, conversation_id) -> AgentState:
        config = {
            'configurable': {
                'thread_id': conversation_id,
            }
        }
        result = await self.graph.aget_state(config)
        return AgentState(**result.values)
    
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
        return state.preferences
    
    async def update_preferences(self, conversation_id, updates):
        await self.update_state(conversation_id, {
            'preferences': updates,
        })

    async def get_history(self, conversation_id):
        state = await self.get_state(conversation_id)
        history = state.history
        history = list(map(lambda x: x.content, history))
        return history

    async def get_task_status(self, conversation_id, task_id):
        state = await self.get_state(conversation_id)
        tasks = state.tasks
        return tasks.get(task_id, None)
    
    async def execute_query(
        self, 
        conversation_id: Optional[str]=None, 
        message: str | Dict[str, InteractionUpdate] ="",
        use_online_agent: bool = False,
        streaming:bool = False
    ):
        
        msg_id = str(uuid.uuid4())
        config = {
            'configurable': {
                'thread_id': conversation_id,
                'use_llm': use_online_agent,
            }
        }
        inputs = {}
        if isinstance(message, str):
            inputs['history'] = [
                HumanMessage(id=msg_id, content=message),
            ]
        else:
            ref_id, data = list(message.items())[0]
            inputs['history'] = [
                ChatMessage(
                    id=msg_id,
                    role='interaction', 
                    content="", 
                    additional_kwargs={
                        'ref_id': ref_id,
                        'data': data,
                    }
                )
            ]
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
                print(msg)
                msg, metadata = chunk
                yield msg

            elif mode == 'updates' and not streaming:
                event = chunk
                print(event)
                for node_name, updates in event.items():
                    if updates is None:
                        continue
                    # check for new_message
                    elif 'history' in updates:
                        has_new_message = True
            
        after = await self.graph.aget_state(config)
        if not streaming:
            state = AgentState(**after.values)
            yield has_new_message, state
    
