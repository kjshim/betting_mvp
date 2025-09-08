from fastapi import FastAPI
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

from api.routes import router

app = FastAPI(
    title="Betting MVP API",
    description="24h Up/Down betting service",
    version="0.1.0"
)

app.include_router(router)

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