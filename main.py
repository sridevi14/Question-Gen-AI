from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import redis
import os
import time
import logging,json
from rq import Queue
from worker import run_worker

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# Redis connection
redis_conn = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)

# RQ queue
question_queue = Queue(connection=redis_conn)

app = FastAPI()

class QuestionRequest(BaseModel):
    technology_name: str
    concepts: List[str]
    difficulty_level: str
    number_of_questions: int
    company_Id: str

class GetQuestionRequest(BaseModel):
    job_Id: str
    company_Id: str

@app.get("/")
async def root():
    # Find_Duplicate()
    return {"message": "Hello World"}

@app.post("/generate_Question")
async def generate_question(request: QuestionRequest):
    if not request.technology_name or request.technology_name.strip() == "":
        raise HTTPException(status_code=400, detail="Technology name cannot be empty")
    if not request.difficulty_level or request.difficulty_level.strip() == "":
        raise HTTPException(status_code=400, detail="Difficulty level cannot be empty")
    if not request.concepts:
        raise HTTPException(status_code=400, detail="Concepts list cannot be empty.")
    if request.number_of_questions < 1 or request.number_of_questions > 10:
        raise HTTPException(status_code=400, detail="Number of questions must be between 1 and 10")

    job_id = str(int(time.time()))
    redis_conn.set(f"{job_id}:status", "queued")
    question_queue.enqueue(run_worker, request, job_id)
    logger.info(f"Enqueued job with ID: {job_id}")
    return {"job_id": job_id}

@app.post("/getQuestions")
async def get_questions(request: GetQuestionRequest):
    key = f"{request.job_Id}:status"
    redis_data = redis_conn.get(key)
    if redis_data:
        status = redis_data.decode("utf-8")
        if status == "completed":
            data = redis_conn.get(request.job_Id)
            return {"data": json.loads(data)}
    raise HTTPException(status_code=404, detail="Job not found or not completed.")
