from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


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