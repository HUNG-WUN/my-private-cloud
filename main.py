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

app = FastAPI(title="我的終極私人雲端 V5.2", description="支援 Google Drive 同步與檔案刪除")
security = HTTPBasic()

# --- 1. 設定區 ---
SCOPES = ['https://www.googleapis.com/auth/drive']
# 請確保此 ID 正確，且已分享權限給 Service Account Email
PARENT_FOLDER_ID = '1TnRuY-pLaXBo2HQrp6Zf_MthYblo5ekK'
BACKUP_FILE_NAME = "system_backup.json"


def get_drive_service():
    env_creds = os.getenv('GOOGLE_CREDENTIALS_JSON')
    try:
        if env_creds:
            info = json.loads(env_creds)
            creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        else:
            creds = service_account.Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"Drive Auth Error: {e}")
        return None


# --- 2. 備份與同步邏輯 ---
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
    except Exception as e:
        print(f"Backup Error: {e}")


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
    except Exception as e:
        print(f"Restore Error: {e}")


# --- 3. 初始化 ---
def init_db():
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT)")
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, drive_file_id TEXT, upload_date DATETIME DEFAULT CURRENT_TIMESTAMP, owner_id INTEGER, FOREIGN KEY(owner_id) REFERENCES users(id))")
    conn.commit();
    conn.close()
    sync_from_cloud()


init_db()


# --- 4. 路由實作 ---
def get_user(creds: HTTPBasicCredentials = Depends(security)):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, username FROM users WHERE username=? AND password=?", (creds.username, creds.password))
    user = cursor.fetchone()
    conn.close()
    if not user: raise HTTPException(status_code=401, detail="驗證失敗")
    return {"id": user[0], "username": user[1]}


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


@app.get("/download/{file_id}", tags=["檔案操作"])
async def download(file_id: int, u=Depends(get_user)):
    conn = sqlite3.connect("my_cloud.db");
    cursor = conn.cursor()
    cursor.execute("SELECT name, drive_file_id FROM files WHERE id=? AND owner_id=?", (file_id, u["id"]))
    res = cursor.fetchone();
    conn.close()
    if not res: raise HTTPException(404, "找不到檔案")

    service = get_drive_service()
    request = service.files().get_media(fileId=res[1])
    fh = io.BytesIO();
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done: _, done = downloader.next_chunk()
    fh.seek(0)
    return StreamingResponse(fh, media_type="application/octet-stream",
                             headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(res[0])}"})


# 補回刪除功能
@app.delete("/delete/{file_id}", tags=["檔案操作"])
async def delete(file_id: int, u=Depends(get_user)):
    conn = sqlite3.connect("my_cloud.db");
    cursor = conn.cursor()
    cursor.execute("SELECT drive_file_id FROM files WHERE id=? AND owner_id=?", (file_id, u["id"]))
    res = cursor.fetchone()
    if not res: conn.close(); raise HTTPException(404, "權限不足或檔案不存在")

    # 刪除 Drive 實體
    try:
        get_drive_service().files().delete(fileId=res[0]).execute()
    except:
        pass

    cursor.execute("DELETE FROM files WHERE id=?", (file_id,))
    conn.commit();
    conn.close();
    sync_to_cloud()
    return {"message": "檔案已移除"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))