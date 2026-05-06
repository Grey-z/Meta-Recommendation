from contextlib import asynccontextmanager
from fastapi import FastAPI
from metarec.service import MetaRecService
import importlib

@asynccontextmanager
async def lifespan(app: FastAPI):
    # initialize service
    app.state.service = MetaRecService()
    
    # get frontend path
    frontend_found = False
    for candidate in [
        'frontend-dist', 
        'dist', 
        '../../../Metarec-ui/dist',
    ]:
        frontend_dist = importlib.resources.files('metarec') / candidate
        if frontend_dist.is_dir():
            frontend_found = True
            app.state.frontend_dist = frontend_dist
            break

    if frontend_found:
        print(app.state.frontend_dist)
    else:
        print('frontend-dist not found')
    
    print('Service ready')
    yield
