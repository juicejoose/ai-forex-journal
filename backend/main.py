from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)

class JournalInput(BaseModel):
    pair: str
    notes: str


@app.get("/")
def home():
    return {"message": "Forex AI Journal API is running"}


@app.post("/journal/preview")
def preview_journal(entry: JournalInput):
    return {
        "pair": entry.pair,
        "notes": entry.notes,
    }