from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from influx_client import influx_service
from routers import zones

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdownl
    influx_service.close()

app = FastAPI(
    title="Frost-IoE Core API",
    description="Independent Cold Storage Monitoring & Compliance API (Sarawak, Malaysia)",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Middleware 
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Core Endpoints
app.include_router(zones.router)

@app.get("/", tags=["Health"])
def root():
    return {
        "system": "Frost-IoE Core API",
        "status": "online",
        "mock_mode": settings.USE_MOCK_DATA,
        "docs_url": "/docs"
    }

@app.get("/api/health", tags=["Health"])
def health_check():
    return {
        "status": "healthy",
        "influx_host": settings.INFLUX_HOST,
        "bucket": settings.INFLUX_BUCKET,
        "mock_mode": settings.USE_MOCK_DATA
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.BACKEND_HOST, port=settings.BACKEND_PORT, reload=True)