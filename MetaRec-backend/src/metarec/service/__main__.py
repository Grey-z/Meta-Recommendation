from metarec.legacy.main import app as legacy_app
from metarec.service.router import create_router as create_service_router
from metarec.service.lifespan import lifespan

import logging
import os
import importlib.resources
import uvicorn

from fastapi import FastAPI
from fastapi import Request
from fastapi import HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger('metarec')

def create_app():
    app = FastAPI(lifespan=lifespan)
    app.mount('/v1', legacy_app)
    app.include_router(create_service_router())
    return app

app = create_app()

@app.middleware('http')
async def log_with_operation_id(request: Request, call_next):
    response = await call_next(request)
    
    route = request.scope.get('route')
    
    op_id = getattr(route, 'operation_id', None) if route else None
    
    if op_id is None:
        msg = '%s - "%s %s" - %d' % (
            request.client.host,
            request.method,
            request.url.path,
            response.status_code,
        )
    else:
        msg = '%s - "%s %s | %s" - %d' % (
            request.client.host,
            request.method,
            request.url.path,
            op_id,
            response.status_code,
        )
        msg = op_id
        logger.info(msg)
    return response

@app.get('/', include_in_schema=False)
def serve_index(request: Request):
    file_path = request.app.state.frontend_dist / 'index.html'
    if file_path.is_file():
        return FileResponse(file_path)
    return { "message": "MetaRec API", "docs": "/docs"}

@app.get('/{full_path:path}', include_in_schema=False)
def serve_spa(request: Request, full_path: str):
    # serve asset files
    file_path = request.app.state.frontend_dist / full_path
    if file_path.is_file():
        return FileResponse(file_path)
    
    # serve routes
    if full_path in [
        'MetaRec',
        'research',
        'debug'
    ]:
        file_path = request.app.state.frontend_dist / 'index.html'
        if file_path.is_file():
            return FileResponse(file_path)

    raise HTTPException(status_code=404, detail="Not found")

def main():
    port = int(os.getenv('PORT', 8000))
    host = '127.0.0.1'

    config = uvicorn.Config(
        app,
        port=port,
        host=host,
        log_level='info',
    )
    
    server = uvicorn.Server(config)
    server.run()

if __name__ == '__main__':
    main()
