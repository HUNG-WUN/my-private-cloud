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

app = FastAPI(title="永久化私人雲端 (G-Drive Sync)")
security = HTTPBasic()

# --- 1. Google Drive 設定 ---
SCOPES = ['https://www.googleapis.com/auth/drive']
PARENT_FOLDER_ID = '你的資料夾ID'
USERS_JSON_NAME = "users_backup.json"  # 存在雲端的文件名


def get_drive_service():
    env_creds = os.getenv('GOOGLE_CREDENTIALS_JSON')
    if env_creds:
        info = json.loads(env_creds)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        creds = service_account.Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)


# --- 2. 核心功能：同步使用者資料 ---

def sync_users_from_drive():
    """從 Google Drive 下載使用者名單並寫入本地 SQL"""
    service = get_drive_service()
    query = f"name = '{USERS_JSON_NAME}' and '{PARENT_FOLDER_ID}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id)").execute()
    files = results.get('files', [])

    if files:
        file_id = files[0]['id']
        request = service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        data = json.loads(fh.getvalue().decode())
        conn = sqlite3.connect("my_cloud.db")
        cursor = conn.cursor()
        for user in data:
            try:
                cursor.execute("INSERT OR IGNORE INTO users (username, password) VALUES (?, ?)",
                               (user['username'], user['password']))
            except:
                pass
        conn.commit()
        conn.close()


def sync_users_to_drive():
    """將本地 SQL 的使用者名單上傳至 Google Drive 覆蓋舊檔"""
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute("SELECT username, password FROM users")
    users = [{"username": r[0], "password": r[1]} for r in cursor.fetchall()]
    conn.close()

    service = get_drive_service()
    content = json.dumps(users).encode()
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype='application/json')

    # 先找舊檔案 ID
    query = f"name = '{USERS_JSON_NAME}' and '{PARENT_FOLDER_ID}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id)").execute()
    files = results.get('files', [])

    if files:
        service.files().update(fileId=files[0]['id'], media_body=media).execute()
    else:
        file_metadata = {'name': USERS_JSON_NAME, 'parents': [PARENT_FOLDER_ID]}
        service.files().create(body=file_metadata, media_body=media).execute()


# --- 3. 初始化與資料庫 ---

def init_db():
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT)")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, drive_file_id TEXT, 
            upload_date DATETIME DEFAULT CURRENT_TIMESTAMP, owner_id INTEGER,
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    """)
    conn.commit()
    conn.close()

    # 啟動時先從雲端抓回使用者名單
    try:
        sync_users_from_drive()
    except:
        print("首次執行或雲端尚無備份")


init_db()


# --- 4. 註冊功能 (包含同步至雲端) ---

@app.post("/register/", tags=["使用者管理"])
async def register(username: str, password: str):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
        conn.close()
        # 註冊成功後，立刻備份到 Google Drive
        sync_users_to_drive()
        return {"message": "註冊成功且已同步至雲端備份"}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="用戶名已存在")


# --- 5. 權限驗證與其他功能 (與之前相同) ---

def get_current_user(credentials: HTTPBasicCredentials = Depends(security)):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, username FROM users WHERE username = ? AND password = ?",
                   (credentials.username, credentials.password))
    user = cursor.fetchone()
    conn.close()
    if not user: raise HTTPException(status_code=401, detail="驗證失敗")
    return {"id": user[0], "username": user[1]}


@app.post("/upload/", tags=["檔案操作"])
async def upload_file(file: UploadFile = File(...), user=Depends(get_current_user)):
    service = get_drive_service()
    file_metadata = {'name': file.filename, 'parents': [PARENT_FOLDER_ID]}
    content = await file.read()
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=file.content_type)
    drive_file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    drive_id = drive_file.get('id')
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
    res = cursor.fetchone()
    conn.close()
    if not res: raise HTTPException(status_code=404, detail="找不到檔案")
    service = get_drive_service()
    request = service.files().get_media(fileId=res[1])
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done: _, done = downloader.next_chunk()
    fh.seek(0)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(res[0])}"}
    return StreamingResponse(fh, media_type="application/octet-stream", headers=headers)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)