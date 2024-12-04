from fastapi import FastAPI, HTTPException,Header,Depends
from fastapi.security import APIKeyHeader
from pydantic import BaseModel,ValidationError
from typing import List
import redis
import os
import time
import uuid
import logging,json
from rq import Queue
from worker import process_question_generation_task
from db_manager import get_mongo_connection,get_redis_connection
from fastapi.middleware.cors import CORSMiddleware

db = get_mongo_connection()
if db is None:
    print("Database connection failed.")

redis_conn = get_redis_connection()
if redis_conn is None:
    print("Failed to connect to Redis.")

# RQ queue
question_queue = Queue(connection=redis_conn)



# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
API_KEY = os.getenv("API_KEY")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class GenerateQuestionRequestModel(BaseModel):
    technology_name: str
    concepts: List[str]
    difficulty_level: str
    number_of_questions: int
    company_Id: str
    strict_question:bool
class StoreQuestionRequestModel(BaseModel):
    questions:List[int]
    company_Id:str


class QuestionRequestModel(BaseModel):
    job_Id: str


def verify_token(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid token format")
    token = authorization[7:]
    if token != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.post("/generate_ai_question")
async def generate_ai_question(request: GenerateQuestionRequestModel,authorized: bool = Depends(verify_token)):
    valid_technologies = {"React", "Golang", "Python"}

    if not request.technology_name or request.technology_name.strip() not in valid_technologies:
        raise HTTPException(status_code=400, detail="Technology name must be one of: React, Golang, Python")
    if not request.difficulty_level or request.difficulty_level.strip() == "":
        raise HTTPException(status_code=400, detail="Difficulty level cannot be empty")
    if not request.concepts:
        raise HTTPException(status_code=400, detail="Concepts list cannot be empty.")
    if request.number_of_questions < 1 or request.number_of_questions > 10:
        raise HTTPException(status_code=400, detail="Number of questions must be between 1 and 10")

    request.concepts = list({concept.strip().lower() for concept in request.concepts if concept.strip()})
    relevant_docs = list(
    db["generated_questions"].find({
        "companies_used_by": {"$nin": [request.company_Id]},
        "metadata.technology": request.technology_name,
        "metadata.difficulty": request.difficulty_level,
        "question.tags": {"$in": request.concepts},
        "strict_question": request.strict_question,
        **({"generated_by": request.company_Id} if request.strict_question else {})
    }).limit(request.number_of_questions)
)

    Questions = []
    job_id = str(uuid.uuid4())
    if len(relevant_docs) > 0:
        Questions = [doc["question"] for doc in relevant_docs]

        if(len(Questions) == request.number_of_questions):
            redis_conn.set(f"{job_id}:status", "completed")
            data = {
                    "technology": request.technology_name,
                    "difficulty": request.difficulty_level,
                    "total_questions": len(Questions),
                    "questions": Questions
                }
            redis_conn.set(job_id, json.dumps(data))
            return {"data":data,"status":"success","job_id":job_id}
        else:
            print("question found..needed_Question status queued")
            needed_Question =  request.number_of_questions - len(Questions)
            request.number_of_questions = needed_Question

    else:
        print("no question found..status queued")
    redis_conn.set(f"{job_id}:status", "queued")
    question_queue.enqueue(process_question_generation_task, request, job_id, Questions)
    logger.info(f"Enqueued job with ID: {job_id}")
    return {"job_id": job_id,"status":"queued"}


@app.post("/get_questions")
async def get_questions(request: QuestionRequestModel, authorized: bool = Depends(verify_token)):
    key = f"{request.job_Id}:status"
    try:
        status = redis_conn.get(key)
        if not status:
            raise HTTPException(
                status_code=404,
                detail=f"No job found for ID: {request.job_Id}"
            )

        status = status.decode("utf-8")
        if status == "completed":
            data = redis_conn.get(request.job_Id)
            if not data:
                raise HTTPException(
                    status_code=500,
                    detail=f"Job {request.job_Id} is marked as completed, but no data is available."
                )
            data = json.loads(data.decode("utf-8"))
            return {
                "status": "completed",
                "data": data
            }

        return {
            "status": status,
            "message": f"Job is currently in {status} status."
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {str(e)}"
        )



@app.post("/store_question")
async def store_question(request: StoreQuestionRequestModel,
                         authorized: bool = Depends(verify_token)):
      try:
        if not request.questions or len(request.questions) == 0:
            raise HTTPException(
                status_code=400,
                detail="The 'Questions' list cannot be empty."
            )
        if not request.company_Id or request.company_Id.strip() == "":
            raise HTTPException(
                status_code=400,
                detail="The 'company_Id' cannot be empty."
            )
        result = db["generated_questions"].update_many(
            {"question.id": {"$in": request.questions}},
            {"$addToSet": {"companies_used_by": request.company_Id}},
            upsert=False
        )
        if result.matched_count == 0:
            raise HTTPException(
                status_code=404,
                detail="No matching questions found for the provided IDs."
            )
        return {
            "message": "Questions updated successfully.",
            "matched_count": result.matched_count,
            "modified_count": result.modified_count
        }
      except ValidationError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid request data: {e.errors()}"
        )
      except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {str(e)}"
        )

