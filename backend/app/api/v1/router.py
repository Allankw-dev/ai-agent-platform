from fastapi import APIRouter

from app.api.v1 import agents, auth, health, invitations, organizations, runs, tools

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(organizations.router)
api_router.include_router(invitations.router)
api_router.include_router(agents.router)
api_router.include_router(runs.router)
api_router.include_router(tools.router)
