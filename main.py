# main.py
from fastapi import FastAPI, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.params import Query
from pydantic import BaseModel
from serpapi import GoogleSearch
from uuid import uuid4
import os, shutil, sqlite3, json
from dotenv import load_dotenv

# 環境変数を読み込む
load_dotenv()

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DB_PATH = "faces.db"
UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# SQLite setup - 拡張版
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        # 既存のfacesテーブル
        conn.execute('''CREATE TABLE IF NOT EXISTS faces (
            id INTEGER PRIMARY KEY,
            image_id TEXT,
            name TEXT,
            linkedin_url TEXT,
            x REAL,
            y REAL
        )''')
        # 新規：画像情報テーブル
        conn.execute('''CREATE TABLE IF NOT EXISTS images (
            image_id TEXT PRIMARY KEY,
            title TEXT,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
init_db()

@app.get("/", response_class=HTMLResponse)
def host_page(request: Request):
    # アップロード済みの画像一覧を取得
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        images = conn.execute(
            "SELECT i.*, COUNT(f.id) as face_count FROM images i "
            "LEFT JOIN faces f ON i.image_id = f.image_id "
            "GROUP BY i.image_id ORDER BY i.upload_date DESC"
        ).fetchall()
    
    return templates.TemplateResponse("host.html", {
        "request": request,
        "images": [dict(img) for img in images]
    })

@app.post("/upload")
def upload_image(image: UploadFile, title: str = Form(...)):
    print("upload")
    image_id = str(uuid4())
    filepath = f"{UPLOAD_FOLDER}/{image_id}.jpg"
    with open(filepath, "wb") as f:
        shutil.copyfileobj(image.file, f)
    
    # 画像情報をDBに保存
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO images (image_id, title) VALUES (?, ?)", (image_id, title))
    
    return {"link": f"/photo/{image_id}", "admin_link": f"/admin/{image_id}", "image_id": image_id}

@app.get("/photo/{image_id}", response_class=HTMLResponse)
def participant_page(request: Request, image_id: str):
    return templates.TemplateResponse("participant.html", {"request": request, "image_id": image_id})

# 新規：管理画面
@app.get("/admin/{image_id}", response_class=HTMLResponse)
def admin_page(request: Request, image_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        # 画像情報を取得
        image_info = conn.execute("SELECT * FROM images WHERE image_id = ?", (image_id,)).fetchone()
        # 登録済み顔情報を取得
        faces = conn.execute("SELECT * FROM faces WHERE image_id = ?", (image_id,)).fetchall()
    
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "image_id": image_id,
        "image_info": dict(image_info) if image_info else {},
        "faces": [dict(face) for face in faces]
    })

# 新規：管理画面用API - 画像詳細情報取得
@app.get("/api/image-details/{image_id}")
def get_image_details(image_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        # 画像情報
        image_info = conn.execute("SELECT * FROM images WHERE image_id = ?", (image_id,)).fetchone()
        # 顔情報
        faces = conn.execute("SELECT * FROM faces WHERE image_id = ?", (image_id,)).fetchall()
    
    return {
        "image": dict(image_info) if image_info else None,
        "faces": [dict(face) for face in faces]
    }

class RegisterInput(BaseModel):
    image_id: str
    x: float
    y: float
    firstname: str
    lastname: str

@app.post("/search_linkedin")
def search_linkedin(data: RegisterInput):
    query = f"{data.firstname} {data.lastname} site:linkedin.com/in"
    
    # 環境変数からAPIキーを取得
    serpapi_key = os.getenv("SERPAPI_KEY")
    if not serpapi_key:
        return {"error": "API key not configured"}
    
    search = GoogleSearch({
        "q": query, 
        "api_key": serpapi_key,
        "hl": "en"
    })
    results = search.get_dict()
    profiles = []
    for r in results.get("organic_results", []):
        if "linkedin.com/in/" in r.get("link", ""):
            profiles.append({
                "name": r.get("title", ""),
                "url": r.get("link", ""),
                "snippet": r.get("snippet", ""),
                "thumbnail": r.get("thumbnail", "")
            })
        if len(profiles) >= 5:
            break
    return profiles

class FinalizeInput(BaseModel):
    image_id: str
    name: str
    linkedin_url: str
    x: float
    y: float

@app.post("/finalize")
def finalize_registration(data: FinalizeInput):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO faces (image_id, name, linkedin_url, x, y) VALUES (?, ?, ?, ?, ?)",
                     (data.image_id, data.name, data.linkedin_url, data.x, data.y))
    return {"status": "success", "image_id": data.image_id}

# 新規：画像ダウンロード
@app.get("/download/{image_id}")
def download_image(image_id: str):
    filepath = f"{UPLOAD_FOLDER}/{image_id}.jpg"
    if os.path.exists(filepath):
        with sqlite3.connect(DB_PATH) as conn:
            title = conn.execute("SELECT title FROM images WHERE image_id = ?", (image_id,)).fetchone()
            filename = f"{title[0]}.jpg" if title else f"photo_{image_id}.jpg"
        return FileResponse(filepath, filename=filename)
    return {"error": "Image not found"}

@app.get("/thanks", response_class=HTMLResponse)
def thanks_page(request: Request, image_id: str = Query(None)):
    return templates.TemplateResponse("thanks.html", {"request": request, "image_id": image_id})