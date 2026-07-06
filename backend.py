import uvicorn
from dotenv import load_dotenv

load_dotenv()

from parking_backend.config import PORT

if __name__ == "__main__":
    print("[ParkX] Starting server...")
    uvicorn.run("parking_backend.main:app", host="0.0.0.0", port=PORT, reload=False)
