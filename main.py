import sqlite3
import io
import mimetypes
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from fastapi.responses import StreamingResponse
from urllib.parse import quote

app = FastAPI(title="Google Drive 私人雲端")
security = HTTPBasic()

# --- 1. 設定 Google Drive API ---
SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'credentials.json'  # 你的 JSON 憑證路徑
# 請填入你共享給服務帳戶的 Google Drive 資料夾 ID
PARENT_FOLDER_ID = '你的資料夾ID'


def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)


# --- 2. 資料庫初始化 (紀錄 Google Drive 的 File ID) ---
def init_db():
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT)")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            drive_file_id TEXT, -- 存儲 Google Drive 的唯一 ID
            upload_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            owner_id INTEGER,
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    """)
    try:
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", ("admin", "123"))
    except:
        pass
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
    if not user: raise HTTPException(status_code=401, detail="驗證失敗")
    return {"id": user[0], "username": user[1]}


# --- 4. 註冊功能 ---
@app.post("/register/", tags=["使用者管理"])
async def register(username: str, password: str):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
        return {"message": "註冊成功"}
    except:
        raise HTTPException(status_code=400, detail="帳號已存在")


# --- 5. 上傳至 Google Drive ---
@app.post("/upload/", tags=["檔案操作"])
async def upload_file(file: UploadFile = File(...), user=Depends(get_current_user)):
    service = get_drive_service()

    # 準備上傳到 Google Drive
    file_metadata = {
        'name': file.filename,
        'parents': [PARENT_FOLDER_ID]
    }
    file_content = await file.read()
    media = MediaIoBaseUpload(io.BytesIO(file_content), mimetype=file.content_type)

    # 執行 Google 上傳
    drive_file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    drive_id = drive_file.get('id')

    # 將 Google Drive ID 存入 SQL
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO files (name, drive_file_id, owner_id) VALUES (?, ?, ?)",
                   (file.filename, drive_id, user["id"]))
    conn.commit()
    conn.close()

    return {"message": "已成功上傳至 Google Drive", "drive_id": drive_id}


# --- 6. 查看檔案清單 ---
@app.get("/files/", tags=["檔案操作"])
async def list_files(user=Depends(get_current_user)):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, upload_date FROM files WHERE owner_id = ?", (user["id"],))
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "date": r[2]} for r in rows]


# --- 7. 從 Google Drive 下載/查看 ---
@app.get("/download/{file_id}", tags=["檔案操作"])
async def download_file(file_id: int, user=Depends(get_current_user)):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, drive_file_id FROM files WHERE id = ? AND owner_id = ?", (file_id, user["id"]))
    result = cursor.fetchone()
    conn.close()

    if not result: raise HTTPException(status_code=404, detail="找不到檔案")

    filename, drive_id = result
    service = get_drive_service()

    # 從 Google Drive 抓取二進位流
    request = service.files().get_media(fileId=drive_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()

    fh.seek(0)
    encoded_filename = quote(filename)
    return StreamingResponse(fh, media_type="application/octet-stream",
                             headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"})