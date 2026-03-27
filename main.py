import sqlite3
import io
import mimetypes
import os
import json
from fastapi import FastAPI, UploadFile, File, HTTPException, Response, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from fastapi.responses import StreamingResponse
from urllib.parse import quote
from typing import List

app = FastAPI(title="我的雲端硬碟 (Google Drive 版)", description="部署於 Render 的私人雲端 API")
security = HTTPBasic()

# --- 1. Google Drive 設定 ---
SCOPES = ['https://www.googleapis.com/auth/drive']
# 重要：請將下方的 ID 換成你 Google Drive 資料夾的實際 ID
PARENT_FOLDER_ID = '你的資料夾ID'


def get_drive_service():
    # 優先從環境變數讀取 JSON 字串 (Render 部署用)
    env_creds = os.getenv('GOOGLE_CREDENTIALS_JSON')

    try:
        if env_creds:
            info = json.loads(env_creds)
            creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        else:
            # 本機開發時讀取實體檔案
            creds = service_account.Credentials.from_service_account_file(
                'credentials.json', scopes=SCOPES)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Google Drive 認證失敗: {e}")
        return None


# --- 2. 資料庫初始化 ---
def init_db():
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    # 用戶表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            username TEXT UNIQUE, 
            password TEXT
        )
    """)
    # 檔案表 (存儲 Google Drive ID)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            drive_file_id TEXT,
            upload_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            owner_id INTEGER,
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()


init_db()


# --- 3. 權限驗證 ---
def get_current_user(credentials: HTTPBasicCredentials = Depends(security)):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, username FROM users WHERE username = ? AND password = ?",
                   (credentials.username, credentials.password))
    user = cursor.fetchone()
    conn.close()

    if not user:
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")
    return {"id": user[0], "username": user[1]}


# --- 4. API 路由 ---

@app.post("/register/", tags=["使用者管理"])
async def register(username: str, password: str):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
        return {"status": "success", "message": f"用戶 {username} 註冊成功"}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="用戶名已存在")
    finally:
        conn.close()


@app.post("/upload/", tags=["檔案操作"])
async def upload_file(file: UploadFile = File(...), user=Depends(get_current_user)):
    service = get_drive_service()
    if not service:
        raise HTTPException(status_code=500, detail="無法連接至 Google Drive")

    # 上傳至 Google Drive
    file_metadata = {'name': file.filename, 'parents': [PARENT_FOLDER_ID]}
    content = await file.read()
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=file.content_type)

    drive_file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    drive_id = drive_file.get('id')

    # 紀錄至本地資料庫
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO files (name, drive_file_id, owner_id) VALUES (?, ?, ?)",
                   (file.filename, drive_id, user["id"]))
    conn.commit()
    conn.close()

    return {"message": "上傳成功", "drive_id": drive_id}


@app.get("/files/", tags=["檔案操作"])
async def list_files(user=Depends(get_current_user)):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, upload_date FROM files WHERE owner_id = ?", (user["id"],))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "date": r[2]} for r in rows]


@app.get("/download/{file_id}", tags=["檔案操作"])
async def download_file(file_id: int, user=Depends(get_current_user)):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, drive_file_id FROM files WHERE id = ? AND owner_id = ?", (file_id, user["id"]))
    result = cursor.fetchone()
    conn.close()

    if not result:
        raise HTTPException(status_code=404, detail="找不到檔案")

    filename, drive_id = result
    service = get_drive_service()

    # 從 Google Drive 串流下載
    request = service.files().get_media(fileId=drive_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()

    fh.seek(0)
    encoded_filename = quote(filename)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"}
    return StreamingResponse(fh, media_type="application/octet-stream", headers=headers)


@app.delete("/delete/{file_id}", tags=["檔案操作"])
async def delete_file(file_id: int, user=Depends(get_current_user)):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()

    # 1. 查找 Google Drive ID
    cursor.execute("SELECT drive_file_id FROM files WHERE id = ? AND owner_id = ?", (file_id, user["id"]))
    result = cursor.fetchone()

    if not result:
        conn.close()
        raise HTTPException(status_code=404, detail="檔案不存在")

    drive_id = result[0]

    # 2. 從 Google Drive 刪除
    service = get_drive_service()
    try:
        service.files().delete(fileId=drive_id).execute()
    except Exception as e:
        print(f"Google Drive 刪除失敗 (可能檔案已不存在): {e}")

    # 3. 從資料庫刪除
    cursor.execute("DELETE FROM files WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()

    return {"message": "檔案已成功從雲端刪除"}


# --- 5. 啟動設定 ---
if __name__ == "__main__":
    import uvicorn

    # Render 會自動提供 PORT 環境變數
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)