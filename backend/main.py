from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field
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
    model_config = ConfigDict(str_strip_whitespace=True)

    pair: str = Field(min_length=1)
    notes: str = Field(min_length=1)


@app.get("/")
def home():
    return {"message": "Forex AI Journal API is running"}


@app.post("/journal/preview")
def preview_journal(entry: JournalInput):
    return {
        "pair": entry.pair,
        "notes": entry.notes,
    }