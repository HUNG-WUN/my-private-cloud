<h1>My Private Cloud ☁️🔒</h1>

<p>A self-hosted, high-performance private cloud storage and file management system providing secure user authentication and binary object (BLOB) data management.</p>

<p>
  <a href="https://github.com/HUNG-WUN/my-private-cloud"><img src="https://img.shields.io/badge/GitHub-Repository-blue?logo=github" alt="GitHub Repo"></a>
  <img src="https://img.shields.io/badge/Python-3.9+-green?logo=python" alt="Python Version">
  <img src="https://img.shields.io/badge/FastAPI-0.95+-009688?logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/SQLite3-Cloud-lightgrey?logo=sqlite" alt="SQLite3">
  <img src="https://img.shields.io/badge/License-MIT-yellow" alt="License">
</p>

<hr>

<h2>📌 專案簡介 (Overview)</h2>
<p><b>My Private Cloud</b> 是一個輕量級且高擴充性的私有雲存儲系統。後端採用 Python FastAPI 框架構建 RESTful 介面，支援使用者身份驗證、權限管理，以及大檔案與二進位物件（BLOB）的高效上傳、下載與管理。</p>

<hr>

<h2>✨ 核心功能 (Key Features)</h2>
<ul>
  <li>🔐 <b>使用者身份驗證 (Authentication & Security)</b>：基於 Token 驗證機制，確保帳號資料與雲端檔案存取安全。</li>
  <li>📁 <b>二進位檔案儲存 (BLOB Storage)</b>：支援各類型文件、圖片與媒體檔案的高效傳輸與物件化管理。</li>
  <li>⚡ <b>高效能 API (High Performance API)</b>：使用 FastAPI 提供低延遲、異步處理的 RESTful API 服務。</li>
  <li>🗄️ <b>資料庫連線池 (Database Connection Pool)</b>：結合 SQLite3 / MySQL 輕量資料庫，確保高併發請求下的資料一致性。</li>
  <li>🚀 <b>雲端雲端原生部署 (Cloud Ready)</b>：支援 Docker 容器化打包，可快速部署至 Railway 或 Render 等雲端平台。</li>
</ul>

<hr>

<h2>🛠️ 技術棧 (Tech Stack)</h2>

<table border="1">
  <thead>
    <tr>
      <th>領域</th>
      <th>技術 / 套件</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><b>後端框架 (Backend)</b></td>
      <td>Python 3.9+, FastAPI, Uvicorn, Pydantic</td>
    </tr>
    <tr>
      <td><b>資料庫 (Database)</b></td>
      <td>SQLite3 / MySQL, Connection Pooling</td>
    </tr>
    <tr>
      <td><b>安全性 (Security)</b></td>
      <td>Passlib / OAuth2, JWT Token</td>
    </tr>
    <tr>
      <td><b>部署與開發 (DevOps)</b></td>
      <td>Docker, Railway / Render, Git</td>
    </tr>
  </tbody>
</table>

<hr>

<h2>📁 專案目錄結構 (Directory Structure)</h2>

<pre><code>my-private-cloud/
├── app/                  # 後端核心應用程式碼
│   ├── api/              # RESTful API 路由判斷與控制器
│   ├── core/             # 安全性設定與資料庫連線池管理
│   ├── models/           # 資料庫 Schema 與 Pydantic 模型
│   └── main.py           # FastAPI 主入口檔案
├── storage/              # 本地儲存與 BLOB 檔案緩存區
├── requirements.txt      # Python 專案套件依賴清單
├── Dockerfile            # 容器化建置設定
└── README.md             # 專案說明文件
</code></pre>

<hr>

<h2>🚀 快速開始 (Quick Start)</h2>

<h3>前置需求 (Prerequisites)</h3>
<ul>
  <li><a href="https://git-scm.com/">Git</a></li>
  <li><a href="https://www.python.org/">Python 3.9+</a></li>
</ul>

<h3>1. 克隆儲存庫 (Clone Repository)</h3>
<pre><code>git clone https://github.com/HUNG-WUN/my-private-cloud.git
cd my-private-cloud
</code></pre>

<h3>2. 建立並啟動虛擬環境 (Virtual Environment)</h3>
<pre><code>python -m venv venv

# Windows 啟動虛擬環境：
# venv\Scripts\activate

# macOS / Linux 啟動虛擬環境：
source venv/bin/activate
</code></pre>

<h3>3. 安裝依賴並啟動服務 (Install Dependencies & Run)</h3>
<pre><code>pip install -r requirements.txt
python app/main.py
</code></pre>

<p>💡 服務啟動後，開啟瀏覽器造訪 Swagger API 文件：<code>http://localhost:8000/docs</code></p>

<hr>

<h2>🤝 貢獻指南 (Contributing)</h2>
<p>歡迎提交 Pull Request 或開立 Issues 提出建議與改善方案！</p>
<ol>
  <li>Fork 本專案</li>
  <li>建立功能分支 (<code>git checkout -b feature/AmazingFeature</code>)</li>
  <li>提交變更 (<code>git commit -m 'Add some AmazingFeature'</code>)</li>
  <li>推送至分支 (<code>git push origin feature/AmazingFeature</code>)</li>
  <li>開啟 Pull Request</li>
</ol>

<hr>

<h2>📜 授權條款 (License)</h2>
<p>本專案採用 <a href="LICENSE">MIT License</a> 授權條款。</p>
