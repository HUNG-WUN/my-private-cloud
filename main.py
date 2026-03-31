import sqlite3
import io
import os
import json
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from fastapi.responses import StreamingResponse
from urllib.parse import quote

app = FastAPI(title="私人雲端 V5.4 (穩定版)")
security = HTTPBasic()

# --- 1. 設定 ---
SCOPES = ['https://www.googleapis.com/auth/drive']
PARENT_FOLDER_ID = '1TnRuY-pLaXBo2HQrp6Zf_MthYblo5'
BACKUP_FILE_NAME = "system_backup.json"


def get_drive_service():
    """安全地獲取 Google Drive 服務，若失敗則拋出具體錯誤"""
    env_creds = os.getenv('GOOGLE_CREDENTIALS_JSON')
    if not env_creds:
        raise HTTPException(500, "環境變數 GOOGLE_CREDENTIALS_JSON 缺失")
    try:
        # 清理字串，防止隱形字元干擾
        clean_json = env_creds.strip()
        info = json.loads(clean_json)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        return build('drive', 'v3', credentials=creds)
    except json.JSONDecodeError:
        raise HTTPException(500, "JSON 格式錯誤，請檢查 Render 環境變數是否貼完整")
    except Exception as e:
        raise HTTPException(500, f"Google 認證失敗: {str(e)}")


# --- 2. 備份邏輯 (只在需要時呼叫) ---
def sync_to_cloud():
    try:
        service = get_drive_service()
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
        print(f"備份失敗 (但不中斷程式): {e}")


def sync_from_cloud():
    try:
        service = get_drive_service()
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
        print(f"還原失敗: {e}")


# --- 3. 初始化資料庫 ---
@app.on_event("startup")
def startup_event():
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT)")
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, drive_file_id TEXT, upload_date DATETIME DEFAULT CURRENT_TIMESTAMP, owner_id INTEGER, FOREIGN KEY(owner_id) REFERENCES users(id))")
    conn.commit();
    conn.close()
    sync_from_cloud()


# --- 4. 路由 ---
def get_user(creds: HTTPBasicCredentials = Depends(security)):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, username FROM users WHERE username=? AND password=?", (creds.username, creds.password))
    user = cursor.fetchone()
    conn.close()
    if not user: raise HTTPException(401, "驗證失敗")
    return {"id": user[0], "username": user[1]}


@app.get("/")
def root():
    return {"message": "雲端 API 已連線", "docs": "/docs"}


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
        raise HTTPException(400, "帳號已存在")
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
    try:
        service = get_drive_service()
        # 讀取檔案內容
        file_content = await file.read()

        # 準備上傳至 Google Drive
        meta = {'name': file.filename, 'parents': [PARENT_FOLDER_ID]}
        media = MediaIoBaseUpload(io.BytesIO(file_content), mimetype=file.content_type)

        # 執行上傳
        drive_file = service.files().create(body=meta, media_body=media, fields='id').execute()
        drive_id = drive_file.get('id')

        # 寫入資料庫
        conn = sqlite3.connect("my_cloud.db")
        cursor = conn.cursor()
        cursor.execute("INSERT INTO files (name, drive_file_id, owner_id) VALUES (?, ?, ?)",
                       (file.filename, drive_id, u["id"]))
        conn.commit()
        conn.close()

        # 備份到雲端
        sync_to_cloud()

        return {"message": "上傳成功", "id": drive_id}

    except Exception as e:
        # 這行非常重要：它會把真正的錯誤原因回傳給你的 Curl
        import traceback
        error_details = traceback.format_exc()
        print(error_details)  # 在 Render Logs 顯示
        raise HTTPException(status_code=500, detail=f"上傳崩潰原因: {str(e)}")


@app.delete("/delete/{file_id}", tags=["檔案操作"])
async def delete(file_id: int, u=Depends(get_user)):
    conn = sqlite3.connect("my_cloud.db");
    cursor = conn.cursor()
    cursor.execute("SELECT drive_file_id FROM files WHERE id=? AND owner_id=?", (file_id, u["id"]))
    res = cursor.fetchone()
    if not res: conn.close(); raise HTTPException(404, "檔案不存在")

    try:
        service = get_drive_service()
        service.files().delete(fileId=res[0]).execute()
    except:
        pass

    cursor.execute("DELETE FROM files WHERE id=?", (file_id,))
    conn.commit();
    conn.close();
    sync_to_cloud()
    return {"message": "檔案已移除"}