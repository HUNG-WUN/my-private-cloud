import json
import io
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# ================= 參數設定區 =================
# 1. 確保路徑正確，使用原始字串 (r) 避免反斜線問題
BASE_PATH = r"C:\Users\s4111\PycharmProjects\my-private-cloud"
FILE_NAME = "credentials.json"
JSON_FILE_PATH = os.path.join(BASE_PATH, FILE_NAME)

# 2. 你的資料夾 ID (確認是 33 位元那個)
PARENT_FOLDER_ID = '1ixe4mIht3CcaYlYLhp3ss22uKDXPcl8Y'


# =============================================

def test_google_drive():
    try:
        print(f"⏳ 正在讀取認證檔案: {JSON_FILE_PATH}")

        if not os.path.exists(JSON_FILE_PATH):
            print(f"❌ 錯誤：找不到 {FILE_NAME}，請檢查檔案是否在該資料夾下。")
            return

        with open(JSON_FILE_PATH, 'r', encoding='utf-8') as f:
            info = json.load(f)

        # 關鍵修正：修復私鑰中的換行符號
        if "private_key" in info:
            info["private_key"] = info["private_key"].replace("\\n", "\n")

        print("⏳ 正在驗證服務帳號權限...")
        creds = service_account.Credentials.from_service_account_info(
            info,
            scopes=['https://www.googleapis.com/auth/drive']
        )
        service = build('drive', 'v3', credentials=creds)

        print(f"✅ 認證成功！Email: {info['client_email']}")
        print(f"⏳ 正在嘗試上傳測試檔案到資料夾: {PARENT_FOLDER_ID}")

        # 設定檔案元數據
        file_metadata = {
            'name': 'GAVIN_FINAL_TEST_SUCCESS.txt',
            'parents': [PARENT_FOLDER_ID]
        }

        # 建立測試內容
        content = f"上傳測試成功！\n執行時間: 2026-03-31\n上傳者: {info['client_email']}"
        media = MediaIoBaseUpload(
            io.BytesIO(content.encode('utf-8')),
            mimetype='text/plain'
        )

        # 執行上傳，務必帶上 supportsAllDrives=True 來解決 Quota 問題
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id',
            supportsAllDrives=True,  # 關鍵：允許上傳到共有/他人資料夾
            supportsTeamDrives=True  # 雙重保險
        ).execute()

        print("-" * 30)
        print(f"🎉 恭喜 Gavin！檔案已成功上傳！")
        print(f"📄 Google Drive 檔案 ID: {file.get('id')}")
        print(f"👉 快去網頁版資料夾看看，應該會看到 GAVIN_FINAL_TEST_SUCCESS.txt")
        print("-" * 30)

    except Exception as e:
        print(f"\n❌ 發生錯誤！")
        error_msg = str(e)
        if "storageQuotaExceeded" in error_msg:
            print("原因：儲存空間不足。")
            print("解決：請確認你是否已在網頁版將資料夾『共用』給服務帳號 Email，並設為『編輯者』。")
        elif "404" in error_msg:
            print("原因：找不到資料夾。請檢查 PARENT_FOLDER_ID 是否正確。")
        else:
            print(f"具體錯誤訊息內容: {error_msg}")


if __name__ == "__main__":
    test_google_drive()