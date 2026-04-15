from fastapi import APIRouter
from fastapi import Request
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from typing import List, Dict, Any, Optional
import json
import random

# data models
from metarec.service.models import VersionResponse
from metarec.service.models import HealthResponse
from metarec.service.models import ConfigResponse
from metarec.service.models import TaskStatusAPI
from metarec.service.models import QueryData, RecommendationRequest, RecommendationResponseAPI
from metarec.service.models import ThinkingStepAPI
from metarec.service.models import ConfirmationRequestAPI
from metarec.service.models import CreateConversationRequest
from metarec.service.models import UpdateConversationRequest
from metarec.service.models import UserPreferencesResponse 
from metarec.service.models import UpdateConversationPreferencesRequest
from metarec.service.models import PreferencesResponse
from metarec.service.models import UpdatePreferencesResponse, UpdatePreferencesRequest
from metarec.service.models import AddMessageRequest
from metarec.service.models import SuccessResponse 
from metarec.service.models import ConversationData
from metarec.service.models import ConversationSummary
from metarec.service.models import MessageData 

from langchain_core.messages import HumanMessage, AIMessage, ChatMessage, SystemMessage

VERSION_STRING = '1.0.0'

router = APIRouter(
    prefix="/v2/api",
    tags=["MetaRec Service (v2)"],
)

def map_conversation_from_state(user_id, conversation_id, state, summary=False):
    messages = list(map(lambda m: MessageData(
        content=m.content,
        role='user' if isinstance(m, HumanMessage) else 'assistant',
    ), state.get('history', [])))
    last_message = messages[-1].content if len(messages) > 0 else "Start a new conversation..."
    if summary:
        as_model = ConversationSummary(
            id=conversation_id,
            title=state['title'],
            last_message=last_message,
            model=state['model'],
            message_count=len(messages),
            timestamp=state['timestamp'],
            updated_at=state['updated_at'],
        )
    else:
        as_model = ConversationData(
            id=conversation_id,
            user_id=user_id,
            title=state['title'],
            model=state['model'],
            last_message=last_message,
            timestamp=state['timestamp'],
            updated_at=state['updated_at'],
            preferences={},
            messages=messages,
        )
    return as_model


# These mirror v1 api endpoints
@router.get("/", operation_id="get_version", response_model=VersionResponse)
async def get_version(request: Request):
    """
    返回API信息
    
    Returns:
        API基本信息
    """
    return VersionResponse(
        message="MetaRec API is running!", 
        version=VERSION_STRING,
    )

@router.get("/health", operation_id="health_check", response_model=HealthResponse)
async def get_version(request: Request):
    """
    健康检查
    
    Returns:
        服务健康状态
    """
    now = request.app.state.service.time.now()
    return HealthResponse(
        status="healthy",
        timestamp=now,
    )

@router.get("/config", operation_id="get_config", response_model=ConfigResponse)
async def get_config(request: Request):
    """
    返回API信息
    
    Returns:
        API基本信息
    """
    return ConfigResponse(
        googleMapsApiKey="",
    )

@router.post("/process", operation_id="recommend", response_model=RecommendationResponseAPI)
async def process(
    request: Request, 
    data: RecommendationRequest | QueryData
):
    """ 
    Process user message. 
    """

    if isinstance(data, RecommendationRequest):
        data = data.query_data
    
    print(data.conversation_history)
    service = request.app.state.service
    query_message = data.query
    use_online_agent = data.use_online_agent
    conversation_id = data.conversation_id
    user_id = data.user_id
    
    if conversation_id is None:
        raise HTTPException(
            status_code=500,
            detail="Missing conversation_id in request",
        )

    valid = await service.session.has_conversation(user_id, conversation_id)
    if not valid:
        raise HTTPException(
            status_code=500,
            detail="Not authorized or not found"
        )
    
    _result = None
    async for result in service.conversation.execute_query(conversation_id, query_message, use_online_agent, streaming=False):
        _result = result

    has_new_message, state = _result
    llm_reply = state.values.get('history')[-1].content if has_new_message else None
    llm_reply = None
    
    task_id = str(random.random())[:10]
    thinking_steps = None
    thinking_steps = [
        ThinkingStepAPI(
            step="0",
            description="placeholder",
            status="processing",
            details=f'Task ID: {task_id}'
        )
    ]
    
    intent = 'confirmation_no'
    intent = None
    
    confirmation_request=ConfirmationRequestAPI(
        message="placeholder",
        preferences={},
        needs_confirmation=True
    )
    confirmation_request = None
            

    return RecommendationResponseAPI(
        intent=intent,
        restaurants=[],
        llm_reply=llm_reply,
        thinking_steps=thinking_steps,
        confirmation_request=confirmation_request,
        preferences={},
    )

# stream response
@router.post("/process/stream", operation_id="recommend_stream")
async def process_stream(
    request: Request, 
    data: RecommendationRequest | QueryData
):
    """ Process user message, with response streaming. """
    service = request.app.state.service
    if isinstance(data, RecommendationRequest):
        data = data.query_data
    
    print(data.conversation_history)
    conversation_id = data.conversation_id
    user_id = data.user_id
    use_online_agent = data.use_online_agent
    query_message = data.query

    if conversation_id is None:
        raise HTTPException(
            status_code=500,
            detail="Missing conversation_id in request",
        )

    valid = await service.session.has_conversation(user_id, conversation_id)
    if not valid:
        raise HTTPException(
            status_code=500,
            detail="Not authorized or not found"
        )

    async def generator():
        async for msg in service.conversation.execute_query(conversation_id, query_message, use_online_agent, streaming=True):
            chunk_data = {
                'content': msg.content,
                'done': False
            }
            chunk_data_str = json.dumps(chunk_data)
            yield f'data: {chunk_data_str}\n\n'

        chunk_data = {
            'content': '',
            'done': True,
        }
        chunk_data_str = json.dumps(chunk_data)
        yield f'data: {chunk_data_str}\n\n'

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # 禁用 nginx 缓冲
        }
    )
    
@router.get("/status/{task_id}", response_model=TaskStatusAPI, operation_id="get_task_status")
async def get_task_status(
    request: Request, 
    task_id: str,
    user_id: Optional[str] = None, # query param
    conversation_id: Optional[str] = None, # query param
):
    """ Get status of task """
    service = request.app.state.service
    valid = await service.session.has_conversation(user_id, conversation_id)
    if not valid:
        raise HTTPException(
            status_code=500,
            detail="Not authorized or not found"
        )
    
    task_status = await service.conversation.get_task_status(conversation_id, task_id)
    if task_status is not None:
        return task_status
    
    progress = int(100 * random.random())
    status = 'processing'
    result = None
    if progress > 80:
        progress = 100
        status = 'completed'
        result = RecommendationResponseAPI(
            intent="confirmation_no",
            restaurants=[],
            llm_reply="completed placeholder",
            thinking_steps=None,
            confirmation_request=None,
            preferences={},
        )
    elif progress < 10:
        raise HTTPException(
            status_code=404,
            detail="task not found"
        )
    
    return TaskStatusAPI(
        task_id=task_id,
        progress=progress,
        status=status,
        message=f'placeholder progress = {progress}',
        result=result,
    )

@router.post("/update-preferences", response_model=UpdatePreferencesResponse, operation_id="update_preferences")
async def update_preferences(
    request: Request, 
    data: UpdatePreferencesRequest | Dict[str, Any],
):
    """ 
    Update user session-level preferences.

    Note: For conversation specific preferences, use POST /conversation/{user_id}/{conversation_id}/preferences
    """
    service = request.app.state.service

    if isinstance(data, UpdatePreferencesRequest):
        data = data.preferences_data

    if 'user_id' not in data:
        raise HTTPException(
            status_code=500,
            detail="Missing user_id",
        )

    user_id = data['user_id']
    del data['user_id']

    await service.session.update_preferences(user_id, data)
    preferences = await service.session.get_preferences(user_id)

    return UpdatePreferencesResponse(
        preferences=preferences,
        message="Preferences updated successfully",
    )

@router.get("/user-preferences/{user_id}", response_model=UserPreferencesResponse, operation_id="get_user_preferences")
async def get_user_preferences(request: Request, user_id: str):
    """ 
    Get user session-level preferences.

    Note: For conversation specific preferences, use GET /conversation/{user_id}/{conversation_id}/preferences
    """
    preferences = await service.session.get_preferences(user_id)
    return UserPreferencesResponse(
        user_id=user_id,
        preferences=preferences
    )

@router.get("/conversations/{user_id}", response_model=List[ConversationSummary], operation_id="get_conversations")
async def get_conversations(request: Request, user_id: str):
    service = request.app.state.service
    conversation_ids = await service.session.get_conversations(user_id)
    conversations = []
    for conversation_id in conversation_ids:
        state = await service.conversation.get_state(conversation_id)
        summary = map_conversation_from_state(user_id, conversation_id, state, summary=True)
        conversations.append(summary)
    return conversations

@router.get("/conversations/{user_id}/{conversation_id}", response_model=ConversationData, operation_id="get_conversation")
async def get_conversation(request: Request, user_id: str, conversation_id: str):
    service = request.app.state.service
    valid = await service.session.has_conversation(user_id, conversation_id)
    if not valid:
        raise HTTPException(
            status_code=500,
            detail="Not authorized or not found"
        )
    state = await service.conversation.get_state(conversation_id)
    conversation = map_conversation_from_state(user_id, conversation_id, state, summary=False)
    return conversation

@router.post("/conversations/{user_id}", response_model=ConversationData, operation_id="create_conversation")
async def create_conversation(request: Request, user_id: str, data: CreateConversationRequest):
    service = request.app.state.service

    # update session data conversation list
    conversation_id = await service.session.create_conversation(user_id)
    now = service.time.now()
    
    # initial state for conversation
    conversation_id = await service.conversation.init(conversation_id, {
        'title': data.title,
        'model': data.model,
        'timestamp': now,
        'updated_at': now,
    })
    state = await service.conversation.get_state(conversation_id)
    conversation = map_conversation_from_state(user_id, conversation_id, state, summary=False)
    return conversation

@router.put("/conversations/{user_id}/{conversation_id}", response_model=ConversationData, operation_id="update_conversation")
async def update_conversation(request: Request, user_id: str, conversation_id: str, data: UpdateConversationRequest):
    service = request.app.state.service
    valid = await service.session.has_conversation(user_id, conversation_id)
    if not valid:
        raise HTTPException(
            status_code="500",
            detail="Not authorized or not found"
        )
    
    updates  = {}
    n_keys = 0
    if data.title is not None:
        updates['title'] = data.title
        n_keys += 1
    if data.model is not None:
        updates['model'] = data.model
        n_keys += 1
    
    if n_keys > 0:
        await service.conversation.update_state(conversation_id, updates)
    
    state = await service.conversation.get_state(conversation_id)
    conversation = map_conversation_from_state(user_id, conversation_id, state, summary=False)
    return conversation

@router.post("/conversations/{user_id}/{conversation_id}/messages", response_model=SuccessResponse, operation_id="add_message")
async def add_message(request: Request, user_id: str, conversation_id: str, data: AddMessageRequest):
    service = request.app.state.service
    now = service.time.now()
    
    valid = await service.session.has_conversation(user_id, conversation_id)
    if not valid:
        raise HTTPException(
            status_code="500",
            detail="Not authorized or not found"
        )

    if data.role == 'user':
        new_message = HumanMessage(content=data.content)
    elif data.role == 'assistant':
        new_message = AIMessage(content=data.content)
    else:
        raise HTTPException(
            status_code="500",
            detail="Invalid message role",
        )

    await service.conversation.update_state(conversation_id, {
        'history': [new_message],
    })
    
    return SuccessResponse(
        success=True,
        message="Message added",
    )

@router.delete("/conversations/{user_id}/{conversation_id}", response_model=SuccessResponse, operation_id="delete_conversation")
async def delect_conversation(request: Request, user_id: str, conversation_id: str):
    service = request.app.state.service
    valid = await service.session.has_conversation(user_id, conversation_id)
    if not valid:
        raise HTTPException(
            status_code=500,
            detail="Not authorized or not found"
        )
    
    await service.session.delete_conversation(user_id, conversation_id)
    success = await service.session.has_conversation(user_id, conversation_id)
    return SuccessResponse(
        success=success,
        message="Conversation deleted" if success else "Failed to delete conversation",
    )

@router.get(
    "/conversations/{user_id}/{conversation_id}/preferences", 
    response_model=PreferencesResponse, 
    operation_id="get_conversation_preferences"
)
async def get_conversation_preferences(request: Request, user_id: str, conversation_id: str):
    service = request.app.state.service
    valid = await service.session.has_conversation(user_id, conversation_id)
    if not valid:
        raise HTTPException(
            status_code=500,
            detail="Not authorized or not found"
        )

    preferences = await service.conversation.get_preferences(conversation_id)
    return PreferencesResponse(
        preferences=preferences,
    )

@router.put(
    "/conversations/{user_id}/{conversation_id}/preferences", 
    response_model=PreferencesResponse,
    operation_id="update_conversation_preferences"
)
async def update_conversation_preferences(
    request: Request, 
    user_id: str, 
    conversation_id: str, 
    data: UpdateConversationPreferencesRequest | Dict[str, Any],
):
    service = request.app.state.service
    valid = await service.session.has_conversation(user_id, conversation_id)
    if not valid:
        raise HTTPException(
            status_code=500,
            detail="Not authorized or not found"
        )
    
    if isinstance(data, UpdateConversationPreferencesRequest):
        updates = data.preferences_data
    else:
        updates = data
    await service.conversation.update_preferences(conversation_id, updates)
    preferences = await service.conversation.get_preferences(conversation_id)
    return PreferencesResponse(
        preferences=preferences
    )

def create_router():
    """
    Returns an instance of /v2/api router

    TODO: currently just returns the a singleton instance, consider fixing this
    """
    return router
