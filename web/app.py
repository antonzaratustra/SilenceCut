import os
import uuid
import shutil
import asyncio
import subprocess
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

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "tmp", "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "web", "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "web", "templates"))

jobs = {}

class JobStatus:
    def __init__(self, job_id, filename, original_path=None):
        self.job_id = job_id
        self.filename = filename
        self.original_path = original_path # Keep track for full processing after sample
        self.status = "pending"
        self.progress = 0
        self.result_file = None
        self.error = None
        self.stats = {}
        self.config = {} # Store config to reuse for full processing

async def process_task(job_id: str, input_path: str, config: dict):
    job = jobs[job_id]
    job.config = config
    temp_sample_path = None
    
    try:
        sc = SilenceCut(config)
        work_file = input_path

        # Handle Sample Mode
        if config.get('sample'):
            job.status = "preparing_sample"
            job.progress = 5
            sample_dur = config.get('sample_duration', 300)
            temp_sample_path = os.path.join(UPLOAD_DIR, f"sample_{job_id}_{job.filename}")
            
            cmd = [
                "ffmpeg", "-ss", "0", "-t", str(sample_dur),
                "-i", input_path, "-c", "copy", "-y", temp_sample_path
            ]
            process = await asyncio.create_subprocess_exec(*cmd, stderr=subprocess.PIPE)
            await process.wait()
            work_file = temp_sample_path

        job.status = "analyzing"
        job.progress = 15
        
        # Detection
        total_duration = sc.get_video_duration(work_file)
        silence_segments = sc.detect_silence(work_file)
        speech_segments = sc.calculate_speech_segments(silence_segments, total_duration)
        
        job.progress = 40
        job.status = "processing"
        
        # Output setup
        name, ext = os.path.splitext(job.filename)
        suffix = "_sample" if config.get('sample') else "_cut"
        output_filename = f"{name}{suffix}_{uuid.uuid4().hex[:6]}{ext}"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        
        # Execution
        # Note: process_video is synchronous, in a real app we'd wrap this in a thread
        sc.process_video(work_file, output_path, speech_segments)
        
        job.status = "completed"
        job.progress = 100
        job.result_file = output_filename
        job.stats = {
            "is_sample": bool(config.get('sample')),
            "silence_count": len(silence_segments),
            "original_duration": round(total_duration, 2),
            "final_duration": round(sum(s['end'] - s['start'] for s in speech_segments), 2)
        }
    except Exception as e:
        job.status = "failed"
        job.error = str(e)
    finally:
        if temp_sample_path and os.path.exists(temp_sample_path):
            os.remove(temp_sample_path)
        # We DON'T remove the original input_path here anymore so we can re-process it if it's a sample
        # Instead, we should have a cleanup task for old files.

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "presets": PRESETS})

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    job_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{job_id}_{file.filename}")
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    jobs[job_id] = JobStatus(job_id, file.filename, original_path=file_path)
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
    input_path = job.original_path
    
    config = {
        'threshold': threshold,
        'duration': duration,
        'padding_start': padding_start,
        'padding_end': padding_end,
        'min_segment_duration': min_segment,
        'sample': is_sample,
        'sample_duration': sample_duration,
        'output_dir': OUTPUT_DIR
    }
    
    job.status = "starting"
    job.progress = 0
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
