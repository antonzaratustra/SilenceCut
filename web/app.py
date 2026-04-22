import os
import uuid
import shutil
import asyncio
from typing import List, Optional
from fastapi import FastAPI, File, UploadFile, Form, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from silencecut import SilenceCut, PRESETS
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Setup paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "tmp", "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "web", "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "web", "templates"))

# Task storage (in-memory for this prototype)
jobs = {}

class JobStatus:
    def __init__(self, job_id, filename):
        self.job_id = job_id
        self.filename = filename
        self.status = "pending"
        self.progress = 0
        self.result_file = None
        self.error = None
        self.stats = {}

async def process_task(job_id: str, input_path: str, config: dict):
    job = jobs[job_id]
    try:
        job.status = "analyzing"
        job.progress = 10
        
        sc = SilenceCut(config)
        
        # Detection
        total_duration = sc.get_video_duration(input_path)
        silence_segments = sc.detect_silence(input_path)
        speech_segments = sc.calculate_speech_segments(silence_segments, total_duration)
        
        job.status = "processing"
        job.progress = 40
        
        # Output setup
        filename = os.path.basename(input_path)
        name, ext = os.path.splitext(filename)
        output_filename = f"{name}_cut_{job_id}{ext}"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        
        # Execution (synchronous call for now, could be improved with progress parsing)
        sc.process_video(input_path, output_path, speech_segments)
        
        job.status = "completed"
        job.progress = 100
        job.result_file = output_filename
        job.stats = {
            "silence_count": len(silence_segments),
            "original_duration": round(total_duration, 2),
            "final_duration": round(sum(s['end'] - s['start'] for s in speech_segments), 2)
        }
    except Exception as e:
        job.status = "failed"
        job.error = str(e)
    finally:
        # Cleanup uploaded file
        if os.path.exists(input_path):
            os.remove(input_path)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "presets": PRESETS})

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    job_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{job_id}_{file.filename}")
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    jobs[job_id] = JobStatus(job_id, file.filename)
    return {"job_id": job_id, "filename": file.filename}

@app.post("/process/{job_id}")
async def start_process(
    job_id: str,
    background_tasks: BackgroundTasks,
    threshold: float = Form(-30),
    duration: float = Form(0.5),
    padding_start: int = Form(100),
    padding_end: int = Form(150),
    min_segment: float = Form(0.3),
    is_sample: bool = Form(False),
    sample_duration: int = Form(300)
):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    input_path = os.path.join(UPLOAD_DIR, f"{job_id}_{job.filename}")
    
    config = {
        'threshold': threshold,
        'duration': duration,
        'padding_start': padding_start,
        'padding_end': padding_end,
        'min_segment_duration': min_segment,
        'sample': sample_duration if is_sample else None,
        'sample_duration': sample_duration,
        'output_dir': OUTPUT_DIR
    }
    
    background_tasks.add_task(process_task, job_id, input_path, config)
    return {"status": "started", "job_id": job_id}

@app.get("/status/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        return JSONResponse(status_code=404, content={"error": "Job not found"})
    
    job = jobs[job_id]
    return {
        "status": job.status,
        "progress": job.progress,
        "result_file": job.result_file,
        "error": job.error,
        "stats": job.stats
    }

@app.get("/download/{job_id}")
async def download_result(job_id: str):
    if job_id not in jobs or not jobs[job_id].result_file:
        raise HTTPException(status_code=404, detail="Result not ready")
    
    file_path = os.path.join(OUTPUT_DIR, jobs[job_id].result_file)
    return FileResponse(file_path, filename=jobs[job_id].filename.replace(".", "_cut."))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)
