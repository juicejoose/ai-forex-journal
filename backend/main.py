from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def home():
    return {"message": "Forex AI Journal API is running"}