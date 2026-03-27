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

app = FastAPI(title="私人雲端 V5.3 (強效容錯版)")
security = HTTPBasic()

# --- 1. 設定 ---
SCOPES = ['https://www.googleapis.com/auth/drive']
PARENT_FOLDER_ID = '1TnRuY-pLaXBo2HQrp6Zf_MthYblo5ekK'
BACKUP_FILE_NAME = "system_backup.json"


def get_drive_service():
    env_creds = os.getenv('GOOGLE_CREDENTIALS_JSON')
    if not env_creds:
        print("警告：找不到環境變數 GOOGLE_CREDENTIALS_JSON")
        return None
    try:
        # 移除可能存在的首尾空白
        info = json.loads(env_creds.strip())
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Google Drive 認證嚴重錯誤: {str(e)}")
        return None


# --- 2. 備份邏輯 (加入更多 Try-Except 防止崩潰) ---
def sync_to_cloud():
    service = get_drive_service()
    if not service: return
    try:
        conn = sqlite3.connect("my_cloud.db")
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users");
        users = cursor.fetchall()
        cursor.execute("SELECT * FROM files");
        files = cursor.fetchall()
        conn.close()

        backup = {"users": users, "files": files}
        media = MediaIoBaseUpload(io.BytesIO(json.dumps(backup).encode()), mimetype='application/json')
        query = f"name = '{BACKUP_FILE_NAME}' and '{PARENT_FOLDER_ID}' in parents and trashed = false"
        existing = service.files().list(q=query, fields="files(id)").execute().get('files', [])

        if existing:
            service.files().update(fileId=existing[0]['id'], media_body=media).execute()
        else:
            meta = {'name': BACKUP_FILE_NAME, 'parents': [PARENT_FOLDER_ID]}
            service.files().create(body=meta, media_body=media).execute()
        print("備份成功！")
    except Exception as e:
        print(f"備份至雲端失敗: {str(e)}")


def sync_from_cloud():
    service = get_drive_service()
    if not service: return
    try:
        query = f"name = '{BACKUP_FILE_NAME}' and '{PARENT_FOLDER_ID}' in parents and trashed = false"
        res = service.files().list(q=query, fields="files(id)").execute().get('files', [])
        if res:
            request = service.files().get_media(fileId=res[0]['id'])
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done: _, done = downloader.next_chunk()
            data = json.loads(fh.getvalue().decode())
            conn = sqlite3.connect("my_cloud.db")
            cursor = conn.cursor()
            for u in data.get('users', []): cursor.execute("INSERT OR IGNORE INTO users VALUES (?,?,?)", u)
            for f in data.get('files', []): cursor.execute("INSERT OR IGNORE INTO files VALUES (?,?,?,?,?)", f)
            conn.commit();
            conn.close()
            print("還原成功！")
    except Exception as e:
        print(f"從雲端還原失敗: {str(e)}")


# --- 3. 初始化 (確保不因為同步失敗而停止啟動) ---
def init_db():
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT)")
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, drive_file_id TEXT, upload_date DATETIME DEFAULT CURRENT_TIMESTAMP, owner_id INTEGER, FOREIGN KEY(owner_id) REFERENCES users(id))")
    conn.commit();
    conn.close()
    try:
        sync_from_cloud()
    except:
        pass


init_db()


# --- 4. 路由 ---
def get_user(creds: HTTPBasicCredentials = Depends(security)):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, username FROM users WHERE username=? AND password=?", (creds.username, creds.password))
    user = cursor.fetchone()
    conn.close()
    if not user: raise HTTPException(status_code=401, detail="驗證失敗")
    return {"id": user[0], "username": user[1]}


@app.get("/", tags=["系統"])
async def root():
    return {"status": "online", "message": "API 運作中"}


@app.post("/register/", tags=["使用者管理"])
async def register(username: str, password: str):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit();
        sync_to_cloud()
        return {"message": "註冊成功"}
    except:
        raise HTTPException(status_code=400, detail="帳號已存在")
    finally:
        conn.close()


@app.get("/files/", tags=["檔案操作"])
async def list_files(u=Depends(get_user)):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, upload_date FROM files WHERE owner_id=?", (u["id"],))
    rows = cursor.fetchall();
    conn.close()
    return [{"id": r[0], "name": r[1], "date": r[2]} for r in rows]


@app.post("/upload/", tags=["檔案操作"])
async def upload(file: UploadFile = File(...), u=Depends(get_user)):
    service = get_drive_service()
    if not service: raise HTTPException(500, "Google 服務未設定或異常")
    meta = {'name': file.filename, 'parents': [PARENT_FOLDER_ID]}
    media = MediaIoBaseUpload(io.BytesIO(await file.read()), mimetype=file.content_type)
    drive_id = service.files().create(body=meta, media_body=media, fields='id').execute().get('id')
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO files (name, drive_file_id, owner_id) VALUES (?, ?, ?)",
                   (file.filename, drive_id, u["id"]))
    conn.commit();
    conn.close();
    sync_to_cloud()
    return {"message": "上傳成功"}


@app.delete("/delete/{file_id}", tags=["檔案操作"])
async def delete(file_id: int, u=Depends(get_user)):
    conn = sqlite3.connect("my_cloud.db");
    cursor = conn.cursor()
    cursor.execute("SELECT drive_file_id FROM files WHERE id=? AND owner_id=?", (file_id, u["id"]))
    res = cursor.fetchone()
    if not res: conn.close(); raise HTTPException(404, "權限不足或檔案不存在")
    try:
        svc = get_drive_service()
        if svc: svc.files().delete(fileId=res[0]).execute()
    except:
        pass
    cursor.execute("DELETE FROM files WHERE id=?", (file_id,))
    conn.commit();
    conn.close();
    sync_to_cloud()
    return {"message": "檔案已移除"}