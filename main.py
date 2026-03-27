from fastapi import FastAPI
import os

app = FastAPI()

@app.get("/")
def read_root():
    # 測試環境變數是否存在，但不要印出完整內容（安全起見）
    creds = os.getenv("GOOGLE_CREDENTIALS_JSON")
    has_creds = "Yes" if creds else "No"
    return {"status": "Test Mode", "has_environment_variable": has_creds}