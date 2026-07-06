import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import parking_backend.config as config
import parking_backend.database as db
import parking_backend.blynk as blynk
from parking_backend.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()

    poll_task = asyncio.create_task(blynk.poll_loop())
    anomaly_task = asyncio.create_task(blynk.anomaly_loop())

    print(f"[ParkX] Running on http://localhost:{config.PORT}")
    print(f"[ParkX] Polling Blynk every {config.POLL_INTERVAL}s | Anomaly check every {config.ANOMALY_CHECK_INTERVAL}s")

    yield

    poll_task.cancel()
    anomaly_task.cancel()
    print("[ParkX] Shut down.")


app = FastAPI(title="ParkX", version="3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

app.include_router(router)

# Serve frontend as static files so http://localhost:8000 shows the dashboard
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
