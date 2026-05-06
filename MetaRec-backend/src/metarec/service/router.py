from fastapi import APIRouter
from fastapi import Request
from fastapi import Response
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from typing import List, Dict, Any, Optional
import json
import random
import asyncio

# data models
import metarec.service.models as models
import metarec.legacy.models as legacy_models

from langchain_core.messages import HumanMessage, AIMessage, ChatMessage, SystemMessage

VERSION_STRING = '1.0.0'

router = APIRouter(
    prefix="/v2/api",
    tags=["MetaRec Service (v2)"],
)

def create_router():
    return router

# helper functions
def map_conversation_from_state(user_id, conversation_id, state, summary=False) -> models.ConversationData | legacy_models.ConversationSummary:
    messages = [
        models.MessageData(
            id=m.id,
            content=m.content,
            role=('user' if isinstance(m, HumanMessage) else 'assistant')
        ) 
        for m in state.history
        if isinstance(m, (AIMessage, HumanMessage))
    ]

    interactions = { _id: models.InteractionData(
        status=v.status,
        data=v.data,
        type=v.type,
    ) for _id,v in state.interactions.items() }

    last_message = messages[-1].content if len(messages) > 0 else "Start a new conversation..."
    if summary:
        as_model = legacy_models.ConversationSummary(
            id=conversation_id,
            title=state.title,
            last_message=last_message,
            model=state.model,
            message_count=len(messages),
            timestamp=state.timestamp,
            updated_at=state.updated_at,
        )
    else:
        as_model = models.ConversationData(
            id=conversation_id,
            user_id=user_id,
            title=state.title,
            model=state.model,
            last_message=last_message,
            timestamp=state.timestamp,
            updated_at=state.updated_at,
            preferences={},
            messages=messages,
            interactions=interactions,
        )
    return as_model

async def raise_for_missing_conversation(service, user_id, conversation_id):
    valid = await service.session.has_conversation(user_id, conversation_id)
    if not valid:
        raise HTTPException(
            status_code=500,
            detail="Not authorized or not found"
        )

# These mirror v1 api endpoints
@router.get("/", operation_id="get_version", response_model=models.VersionResponse)
async def get_version(request: Request):
    """
    返回API信息
    
    Returns:
        API基本信息
    """
    return models.VersionResponse(
        message="MetaRec API is running!", 
        version=VERSION_STRING,
    )

@router.get("/health", operation_id="health_check", response_model=models.HealthResponse)
async def get_health(request: Request):
    """
    健康检查
    
    Returns:
        服务健康状态
    """
    now = request.app.state.service.time.now()
    return models.HealthResponse(
        status="healthy",
        timestamp=now,
    )

@router.get("/config", operation_id="get_config", response_model=models.ConfigResponse)
async def get_config(request: Request):
    """
    返回API信息
    
    Returns:
        API基本信息
    
    """
    #public apis should not return private API KEYS
    return models.ConfigResponse(
        googleMapsApiKey="TRUNCATED"
    )


@router.post("/process", operation_id="recommend", response_model=models.RecommendationResponseAPI | legacy_models.RecommendationResponseAPI)
async def process(
    request: Request, 
    data: models.RecommendationRequest | models.QueryData
):
    """ 
    Process user message
    """
    # simulate  latency
    await asyncio.sleep(1)

    if isinstance(data, models.RecommendationRequest):
        data = data.query_data
    
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

    await raise_for_missing_conversation(service, user_id, conversation_id)
    
    _result = None
    async for result in service.conversation.execute_query(conversation_id, message=query_message, use_online_agent=use_online_agent, streaming=False):
        _result = result
    has_new_message, state = _result
    conv = map_conversation_from_state(user_id, conversation_id, state, summary=False)
    ret_val = models.RecommendationResponseAPI(
        messages=conv.messages,
        interactions=conv.interactions,
        restaurants=[],
    )
    return ret_val

# stream response
@router.post("/process/stream", operation_id="recommend_stream")
async def process_stream(
    request: Request, 
    data: models.RecommendationRequest | models.QueryData
):
    """ Process user message, with response streaming. """
    service = request.app.state.service
    if isinstance(data, models.RecommendationRequest):
        data = data.query_data
    
    conversation_id = data.conversation_id
    user_id = data.user_id
    use_online_agent = data.use_online_agent
    query_message = data.query

    if conversation_id is None:
        raise HTTPException(
            status_code=500,
            detail="Missing conversation_id in request",
        )

    await raise_for_missing_conversation(service, user_id, conversation_id)

    async def generator():
        async for msg in service.conversation.execute_query(conversation_id, message=query_message, use_online_agent=use_online_agent, streaming=True):
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
    
@router.get("/status/{task_id}", response_model=models.TaskStatusAPI, operation_id="get_task_status")
async def get_task_status(
    request: Request, 
    task_id: str,
    user_id: Optional[str] = None, # query param
    conversation_id: Optional[str] = None, # query param
):
    """ Get status of task """
    service = request.app.state.service
    await raise_for_missing_conversation(service, user_id, conversation_id)
    
    task_status = await service.conversation.get_task_status(conversation_id, task_id)
    if task_status is not None:
        return task_status
    
    progress = int(95 * random.random())
    status = 'processing'
    result = None
    
    return models.TaskStatusAPI(
        task_id=task_id,
        progress=progress,
        status=status,
        message=f'placeholder progress = {progress}',
        result=result,
    )

@router.post("/update-preferences", response_model=models.UpdatePreferencesResponse, operation_id="update_preferences")
async def update_preferences(
    request: Request, 
    data: models.UpdatePreferencesRequest | Dict[str, Any],
):
    """ 
    Update user session-level preferences.

    Note: For conversation specific preferences, use POST /conversation/{user_id}/{conversation_id}/preferences
    """
    service = request.app.state.service

    if isinstance(data, models.UpdatePreferencesRequest):
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

    return models.UpdatePreferencesResponse(
        preferences=preferences,
        message="Preferences updated successfully",
    )

@router.get("/user-preferences/{user_id}", response_model=models.UserPreferencesResponse, operation_id="get_user_preferences")
async def get_user_preferences(request: Request, user_id: str):
    """ 
    Get user session-level preferences.

    Note: For conversation specific preferences, use GET /conversation/{user_id}/{conversation_id}/preferences
    """
    preferences = await service.session.get_preferences(user_id)
    return models.UserPreferencesResponse(
        user_id=user_id,
        preferences=preferences
    )

@router.get("/conversations/{user_id}", response_model=List[legacy_models.ConversationSummary], operation_id="get_conversations")
async def get_conversations(request: Request, user_id: str):
    service = request.app.state.service
    conversation_ids = await service.session.get_conversations(user_id)
    conversations = []
    for conversation_id in conversation_ids:
        state = await service.conversation.get_state(conversation_id)
        summary = map_conversation_from_state(user_id, conversation_id, state, summary=True)
        conversations.append(summary)
    return conversations

@router.get("/conversations/{user_id}/{conversation_id}", response_model=models.ConversationData, operation_id="get_conversation")
async def get_conversation(request: Request, user_id: str, conversation_id: str):
    service = request.app.state.service
    await raise_for_missing_conversation(service, user_id, conversation_id)
    state = await service.conversation.get_state(conversation_id)
    conversation = map_conversation_from_state(user_id, conversation_id, state, summary=False)
    return conversation

@router.post("/conversations/{user_id}", response_model=models.ConversationData, operation_id="create_conversation")
async def create_conversation(request: Request, user_id: str, data: legacy_models.CreateConversationRequest):
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

@router.put("/conversations/{user_id}/{conversation_id}", response_model=models.ConversationData, operation_id="update_conversation")
async def update_conversation(request: Request, user_id: str, conversation_id: str, data: legacy_models.UpdateConversationRequest):
    service = request.app.state.service
    await raise_for_missing_conversation(service, user_id, conversation_id)
    
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

@router.post("/conversations/{user_id}/{conversation_id}/messages", response_model=models.SuccessResponse, operation_id="add_message")
async def add_message(request: Request, user_id: str, conversation_id: str, data: legacy_models.AddMessageRequest):
    service = request.app.state.service
    now = service.time.now()
    
    await raise_for_missing_conversation(service, user_id, conversation_id)

    if data.role == 'user':
        new_message = HumanMessage(content=data.content)
    elif data.role == 'assistant':
        new_message = AIMessage(content=data.content)
    else:
        raise HTTPException(
            status_code="500",
            detail="Invalid message role",
        )

    if False:
        # SKIP
        await service.conversation.update_state(conversation_id, {
            'history': [new_message],
        })
    
    return models.SuccessResponse(
        success=True,
        message="Message added",
    )

@router.delete("/conversations/{user_id}/{conversation_id}", response_model=models.SuccessResponse, operation_id="delete_conversation")
async def delete_conversation(request: Request, user_id: str, conversation_id: str):
    service = request.app.state.service
    await raise_for_missing_conversation(service, user_id, conversation_id)
    
    await service.session.delete_conversation(user_id, conversation_id)
    success = await service.session.has_conversation(user_id, conversation_id)
    return models.SuccessResponse(
        success=success,
        message="Conversation deleted" if success else "Failed to delete conversation",
    )

@router.get(
    "/conversations/{user_id}/{conversation_id}/preferences", 
    response_model=models.PreferencesResponse, 
    operation_id="get_conversation_preferences"
)
async def get_conversation_preferences(request: Request, user_id: str, conversation_id: str):
    service = request.app.state.service
    await raise_for_missing_conversation(service, user_id, conversation_id)

    preferences = await service.conversation.get_preferences(conversation_id)
    return models.PreferencesResponse(
        preferences=preferences,
    )

@router.put(
    "/conversations/{user_id}/{conversation_id}/preferences", 
    response_model=models.PreferencesResponse,
    operation_id="update_conversation_preferences"
)
async def update_conversation_preferences(
    request: Request, 
    user_id: str, 
    conversation_id: str, 
    data: models.UpdateConversationPreferencesRequest | Dict[str, Any],
):
    service = request.app.state.service
    await raise_for_missing_conversation(service, user_id, conversation_id)
    
    if isinstance(data, models.UpdateConversationPreferencesRequest):
        updates = data.preferences_data
    else:
        updates = data
    await service.conversation.update_preferences(conversation_id, updates)
    preferences = await service.conversation.get_preferences(conversation_id)
    return models.PreferencesResponse(
        preferences=preferences
    )

@router.get('/graph_image')
async def get_image(request: Request):
    """
    Vizualization of conversation flow
    """
    service = request.app.state.service
    content = await service.conversation.vizualize()
    return Response(
        content=content,
        media_type="image/png"
    )

