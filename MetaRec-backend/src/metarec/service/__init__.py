import os
import importlib.resources
import uvicorn
from fastapi import FastAPI
from fastapi import HTTPException
from metarec.legacy.main import app as legacy_app
from fastapi.responses import FileResponse


FRONTEND_DIST = importlib.resources.files('metarec') / 'frontend-dist'
app = FastAPI()
app.mount('/v1', legacy_app)

@app.get('/')
def serve_index():
    file_path = FRONTEND_DIST / 'index.html'
    print(file_path, file_path.is_file())
    if file_path.is_file():
        return FileResponse(file_path)
    return { "message": "MetaRec API", "docs": "/docs"}

@app.get('/{full_path:path}')
def serve_spa(full_path: str):
    file_path = FRONTEND_DIST / full_path
    print(file_path, file_path.is_file())
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
