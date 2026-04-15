from ..state import AgentState
import inspect
import asyncio
import functools

def graph_node(name: str):
    def decorator(func):
        
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                return await func(*args, **kwargs)
        else:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)

        func.name = name
        wrapper.name = name
        return wrapper
    return decorator

def no_op(state: AgentState, config):
    """
    no-op
    """
    return {}
