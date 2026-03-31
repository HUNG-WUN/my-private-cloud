import os
import io
import json
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from fastapi.responses import StreamingResponse
from urllib.parse import quote

app = FastAPI(title="永久雲端系統 V6.0", description="使用 Supabase 儲存資料，Google Drive 儲存檔案")
security = HTTPBasic()

# --- 1. 設定區 ---
SCOPES = ['https://www.googleapis.com/auth/drive']
PARENT_FOLDER_ID = '1TnRuY-pLaXBo2HQrp6Zf_MthYblo5'
DATABASE_URL = os.getenv("DATABASE_URL")


# --- 2. 資料庫與 Google 服務連線 ---

def get_db_conn():
    """建立 Supabase (PostgreSQL) 連線"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"資料庫連線失敗: {e}")
        raise HTTPException(status_code=500, detail="無法連線至雲端資料庫")


def get_drive_service():
    """建立 Google Drive API 連線"""
    env_creds = os.getenv('GOOGLE_CREDENTIALS_JSON')
    if not env_creds:
        raise HTTPException(500, "環境變數缺失")
    try:
        info = json.loads(env_creds.strip())
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        raise HTTPException(500, f"Google 認證失敗: {str(e)}")


# --- 3. 權限驗證 ---

def get_current_user(credentials: HTTPBasicCredentials = Depends(security)):
    conn = get_db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT id, username FROM users WHERE username = %s AND password = %s",
                    (credentials.username, credentials.password))
        user = cur.fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="帳號或密碼錯誤")
        return user
    finally:
        cur.close()
        conn.close()


# --- 4. API 路由實作 ---

@app.get("/")
async def root():
    return {"status": "online", "database": "Supabase Connected", "storage": "Google Drive"}


@app.post("/register/", tags=["使用者管理"])
async def register(username: str, password: str):
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, password))
        conn.commit()
        return {"message": "註冊成功，資料已永久儲存"}
    except psycopg2.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=400, detail="帳號已存在")
    finally:
        cur.close()
        conn.close()


@app.get("/files/", tags=["檔案操作"])
async def list_files(user=Depends(get_current_user)):
    conn = get_db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT id, name, upload_date FROM files WHERE owner_id = %s ORDER BY upload_date DESC",
                    (user['id'],))
        return cur.fetchall()
    finally:
        cur.close()
        conn.close()


@app.post("/upload/", tags=["檔案操作"])
async def upload_file(file: UploadFile = File(...), user=Depends(get_current_user)):
    service = get_drive_service()
    content = await file.read()

    # 1. 上傳至 Google Drive
    meta = {'name': file.filename, 'parents': [PARENT_FOLDER_ID]}
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=file.content_type)
    drive_file = service.files().create(body=meta, media_body=media, fields='id').execute()
    drive_id = drive_file.get('id')

    # 2. 寫入 Supabase
    conn = get_db_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO files (name, drive_file_id, owner_id) VALUES (%s, %s, %s)",
                    (file.filename, drive_id, user['id']))
        conn.commit()
        return {"message": "上傳成功", "drive_id": drive_id}
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, detail=f"資料庫寫入失敗: {e}")
    finally:
        cur.close()
        conn.close()


@app.get("/download/{file_id}", tags=["檔案操作"])
async def download_file(file_id: int, user=Depends(get_current_user)):
    conn = get_db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT name, drive_file_id FROM files WHERE id = %s AND owner_id = %s", (file_id, user['id']))
    res = cur.fetchone()
    cur.close()
    conn.close()

    if not res:
        raise HTTPException(status_code=404, detail="找不到檔案")

    service = get_drive_service()
    request = service.files().get_media(fileId=res['drive_file_id'])
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    fh.seek(0)
    return StreamingResponse(
        fh,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(res['name'])}"}
    )


@app.delete("/delete/{file_id}", tags=["檔案操作"])
async def delete_file(file_id: int, user=Depends(get_current_user)):
    conn = get_db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT drive_file_id FROM files WHERE id = %s AND owner_id = %s", (file_id, user['id']))
    res = cur.fetchone()

    if not res:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="檔案不存在")

    # 1. 從 Google Drive 刪除
    try:
        service = get_drive_service()
        service.files().delete(fileId=res['drive_file_id']).execute()
    except Exception as e:
        print(f"Google Drive 刪除失敗 (可能檔案已被手動刪除): {e}")

    # 2. 從 Supabase 刪除
    cur.execute("DELETE FROM files WHERE id = %s", (file_id,))
    conn.commit()
    cur.close()
    conn.close()

    return {"message": "檔案已從資料庫與雲端移除"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))