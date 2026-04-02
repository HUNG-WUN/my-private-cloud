import sqlite3
import mimetypes
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, HTTPException, Response, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from typing import List
from urllib.parse import quote

app = FastAPI(
    title="我的私人雲端系統 V4",
    description="支援用戶註冊、登入、檔案預覽、下載及上傳日期紀錄"
)
security = HTTPBasic()


# --- 1. 資料庫初始化 (新增 upload_date 欄位) ---
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
    # 檔案表：新增 upload_date，預設為當前時間
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            content BLOB,
            upload_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            owner_id INTEGER,
            FOREIGN KEY(owner_id) REFERENCES users(id)
        )
    """)
    # 建立預設帳號
    try:
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", ("admin", "admin123"))
    except sqlite3.IntegrityError:
        pass
    conn.commit()
    conn.close()


init_db()


# --- 2. 權限驗證中間層 ---
def get_current_user(credentials: HTTPBasicCredentials = Depends(security)):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, username FROM users WHERE username = ? AND password = ?",
                   (credentials.username, credentials.password))
    user = cursor.fetchone()
    conn.close()

    if not user:
        raise HTTPException(status_code=401, detail="驗證失敗，請檢查帳號密碼")
    return {"id": user[0], "username": user[1]}


# --- 3. 使用者管理 ---

@app.post("/register/", tags=["使用者管理"])
async def register(username: str, password: str):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return {"status": "success", "message": f"用戶 '{username}' 註冊成功", "id": user_id}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="此用戶名已被佔用")


# --- 4. 檔案操作 ---

@app.post("/upload/", tags=["檔案操作"])
async def upload_file(file: UploadFile = File(...), user=Depends(get_current_user)):
    file_content = await file.read()
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    # 我們不需要手動傳入日期，SQL 會自動生成 CURRENT_TIMESTAMP
    cursor.execute("INSERT INTO files (name, content, owner_id) VALUES (?, ?, ?)",
                   (file.filename, file_content, user["id"]))
    conn.commit()
    file_id = cursor.lastrowid
    conn.close()
    return {"message": "上傳成功", "file_id": file_id}


@app.get("/files/", tags=["檔案操作"])
async def list_files(user=Depends(get_current_user)):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    # 查詢時順便撈出 upload_date
    cursor.execute("SELECT id, name, upload_date FROM files WHERE owner_id = ?", (user["id"],))
    rows = cursor.fetchall()
    conn.close()
    # 回傳 JSON 包含 ID、檔名、上傳日期
    return [
        {
            "id": row[0],
            "name": row[1],
            "upload_date": row[2]  # SQLite 回傳的是字串格式的時間
        } for row in rows
    ]


@app.get("/files/{file_id}", tags=["檔案操作"])
async def view_file(file_id: int, user=Depends(get_current_user)):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, content FROM files WHERE id = ? AND owner_id = ?", (file_id, user["id"]))
    result = cursor.fetchone()
    conn.close()

    if not result:
        raise HTTPException(status_code=404, detail="檔案不存在或無權限")

    filename, content = result
    mime_type, _ = mimetypes.guess_type(filename)
    return Response(content=content, media_type=mime_type or "application/octet-stream")


@app.get("/download/{file_id}", tags=["檔案操作"])
async def download_file(file_id: int, user=Depends(get_current_user)):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute("SELECT name, content FROM files WHERE id = ? AND owner_id = ?", (file_id, user["id"]))
    result = cursor.fetchone()
    conn.close()

    if not result:
        raise HTTPException(status_code=404, detail="檔案不存在或無權限")

    filename, content = result
    encoded_filename = quote(filename)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
    }
    return Response(content=content, media_type="application/octet-stream", headers=headers)


@app.delete("/delete/{file_id}", tags=["檔案操作"])
async def delete_file(file_id: int, user=Depends(get_current_user)):
    conn = sqlite3.connect("my_cloud.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM files WHERE id = ? AND owner_id = ?", (file_id, user["id"]))
    conn.commit()

    if cursor.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404, detail="刪除失敗：檔案不存在或無權限")

    conn.close()
    return {"message": f"檔案 {file_id} 已刪除"}