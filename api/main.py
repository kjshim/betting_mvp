from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

from api.routes import router
from api.admin import router as admin_router

app = FastAPI(
    title="Betting MVP API",
    description="24h Up/Down betting service",
    version="0.1.0"
)

# Mount static files for admin interface
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include routers
app.include_router(router)
app.include_router(admin_router)

@app.get("/")
async def root():
    return {"message": "Betting MVP API", "version": "0.1.0"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)