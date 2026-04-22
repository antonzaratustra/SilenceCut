import os
import uuid
import shutil
import asyncio
import time
import logging
import re
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import FastAPI, File, UploadFile, Form, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from silencecut import SilenceCut, PRESETS
from dotenv import load_dotenv

load_dotenv()

# Logger for cleanup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SilenceCut")

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(BASE_DIR, "tmp", "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "web", "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "web", "templates"))

# Job storage
jobs = {}

class JobStatus:
    def __init__(self, job_id, filename, original_path=None):
        self.job_id = job_id
        self.filename = filename
        self.original_path = original_path
        self.status = "pending"
        self.progress = 0
        self.result_file = None
        self.error = None
        self.stats = {}
        self.created_at = time.time()

# Background task to clean old files
async def cleanup_task():
    ttl_seconds = int(os.getenv("TTL_HOURS", 24)) * 3600
    while True:
        now = time.time()
        logger.info("Running scheduled cleanup...")
        
        for folder in [UPLOAD_DIR, OUTPUT_DIR]:
            if not os.path.exists(folder): continue
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                try:
                    if os.path.isfile(file_path):
                        if now - os.path.getmtime(file_path) > ttl_seconds:
                            os.remove(file_path)
                            logger.info(f"Deleted old file: {filename}")
                except Exception as e:
                    logger.error(f"Error deleting {file_path}: {e}")
        
        await asyncio.sleep(3600) # Run once an hour

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_task())

@app.get("/system_stats")
async def get_system_stats():
    size = 0
    count = 0
    for folder in [UPLOAD_DIR, OUTPUT_DIR]:
        if os.path.exists(folder):
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                if os.path.isfile(file_path):
                    size += os.path.getsize(file_path)
                    count += 1
    return {"count": count, "size_bytes": size}

@app.post("/cleanup")
async def cleanup_all_files():
    deleted_count = 0
    for folder in [UPLOAD_DIR, OUTPUT_DIR]:
        if os.path.exists(folder):
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        deleted_count += 1
                except Exception:
                    pass
    
    # Preserve running jobs, clear the rest
    active_jobs = {k: v for k, v in jobs.items() if v.status in ['starting', 'analyzing', 'processing', 'preparing_sample']}
    jobs.clear()
    jobs.update(active_jobs)
    
    return {"status": "success", "deleted": deleted_count}

async def process_task(job_id: str, input_path: str, config: dict):
    job = jobs[job_id]
    temp_sample_path = None
    try:
        # Extra safety check
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"Source file missing: {input_path}")

        sc = SilenceCut(config)
        work_file = input_path

        if config.get('sample'):
            job.status = "preparing_sample"
            job.progress = 5
            sample_dur = config.get('sample_duration', 300)
            
            # Use a unique name for EACH sample attempt to avoid overwriting conflicts
            attempt_id = uuid.uuid4().hex[:6]
            temp_sample_path = os.path.join(UPLOAD_DIR, f"sample_{attempt_id}_{job.filename}")
            
            cmd = ["ffmpeg", "-ss", "0", "-t", str(sample_dur), "-i", input_path, "-c", "copy", "-y", temp_sample_path]
            process = await asyncio.create_subprocess_exec(*cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
            await process.wait()
            
            # Verify the sample file was actually created and is not empty
            if not os.path.exists(temp_sample_path) or os.path.getsize(temp_sample_path) == 0:
                 raise Exception("Failed to extract video sample (file is empty or missing).")
            
            work_file = temp_sample_path

        job.status = "analyzing"
        job.progress = 15
        await asyncio.sleep(0.5) # Give UI time to catch status
        
        total_duration = sc.get_video_duration(work_file)
        if total_duration <= 0:
            raise ValueError("Could not determine video duration. The file might be corrupted.")

        silence_segments = sc.detect_silence(work_file)
        speech_segments = sc.calculate_speech_segments(silence_segments, total_duration)
        
        job.status = "processing"
        job.progress = 40
        await asyncio.sleep(0.5)
        
        name, ext = os.path.splitext(job.filename)
        suffix = "_sample" if config.get('sample') else "_cut"
        output_filename = f"{name}{suffix}_{uuid.uuid4().hex[:8]}{ext}"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        
        # Move long-running task to a separate thread to keep event loop responsive
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, sc.process_video, work_file, output_path, speech_segments)
        
        if not os.path.exists(output_path):
             raise Exception("Output file was not generated.")

        job.status = "completed"
        job.progress = 100
        job.result_file = output_filename
        job.stats = {
            "is_sample": bool(config.get('sample')),
            "silence_count": len(silence_segments),
            "original_duration": round(total_duration, 2),
            "final_duration": round(sum(s['end'] - s['start'] for s in speech_segments), 2)
        }

        # CRITICAL: Delete original upload ONLY if full processing is done successfully
        if not config.get('sample'):
            if os.path.exists(input_path):
                os.remove(input_path)
                logger.info(f"Deleted source file after full processing: {input_path}")

    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        job.status = "failed"
        job.error = str(e)
        # We NO LONGER delete the input_path on failure. This allows the user to try again.
    finally:
        # Clean up the TEMPORARY sample file only
        if temp_sample_path and os.path.exists(temp_sample_path):
            try:
                os.remove(temp_sample_path)
            except Exception as e:
                logger.warning(f"Could not remove temp sample {temp_sample_path}: {e}")

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
    if not os.path.exists(job.original_path):
         raise HTTPException(status_code=400, detail="Source file already deleted or not found. Please upload again.")

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
    job.error = None # Clear previous errors
    background_tasks.add_task(process_task, job_id, job.original_path, config)
    return {"status": "started", "job_id": job_id}

@app.delete("/job/{job_id}")
async def delete_job(job_id: str):
    if job_id in jobs:
        job = jobs[job_id]
        if job.original_path and os.path.exists(job.original_path):
            os.remove(job.original_path)
        # We keep the result file in output/ for manual cleanup or TTL
        del jobs[job_id]
        return {"status": "deleted"}
    return {"status": "not_found"}

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
    
    job = jobs[job_id]
    file_path = os.path.join(OUTPUT_DIR, job.result_file)
    
    # Smart filename generation
    original_name, ext = os.path.splitext(job.filename)
    # Remove existing _cut or _sample to avoid video_cut_cut_cut.mp4
    clean_name = re.sub(r'(_cut|_sample)+$', '', original_name)
    
    suffix = "_sample" if "_sample" in job.result_file else "_cut"
    download_name = f"{clean_name}{suffix}{ext}"
    
    return FileResponse(file_path, filename=download_name)

if __name__ == "__main__":
    import uvicorn
    import subprocess
    uvicorn.run(app, host="0.0.0.0", port=8765)
