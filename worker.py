import asyncio
import os
import json
import time
import logging
from typing import List
from redis import Redis
from pydantic import BaseModel
from openai import OpenAI
from db_manager import get_mongo_connection,get_redis_connection
from tfidf_minhash import MinHash,FindDuplicates

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY is missing from environment variables.")

# Redis and MongoDB clients
db = get_mongo_connection()
if db is None:
    print("Database connection failed.")

redis_conn = get_redis_connection()
if redis_conn is None:
    print("Failed to connect to Redis.")


# self.db["generated_questions"].create_index([("hash", ASCENDING)])
#         self.db["generated_questions"].create_index([("metadata.technology", ASCENDING)])
#         self.db["generated_questions"].create_index([("question.tags", ASCENDING)])
 # OpenAI client

openai_client = OpenAI(api_key=OPENAI_API_KEY)
minhash = MinHash(num_permutations=100)

# Define request model
class GenerateQuestionRequestModel(BaseModel):
    technology_name: str
    concepts: List[str]
    difficulty_level: str
    number_of_questions: int
    company_Id: str
    strict_question:bool
class Run(BaseModel):
    id: str
    status: str

def fetchAssistant(technology_name:str):
    # Fetch assistant ID from MongoDB
        ai_assistants = db["ai_assistants"]
        doc = ai_assistants.find_one({"technology": technology_name})
        if not doc or "assistant_id" not in doc:
            logger.error(f"No assistant ID found for technology: {technology_name}")
            raise ValueError("Assistant ID not found in database.")
        return doc["assistant_id"]

def create_Thread():
        thread = openai_client.beta.threads.create()
        return thread.id
def create_message(thread_id,content):
        openai_client.beta.threads.messages.create(
            thread_id=thread_id,
            role="user",
            content=content,
        )
def run_assistant(thread_id,assistant_id) -> Run:
     run = openai_client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=assistant_id,
        )
     return run

async def generate_questions(thread_id, run_id: Run, max_retries=60):
     # Wait for the response
        structured_response = None
        for i in range(max_retries):
            logger.info(f"Waiting for OpenAI response... ({i} seconds)")

            result = openai_client.beta.threads.runs.retrieve(
                thread_id=thread_id,
                run_id=run_id
            )
            if result.status == "completed":
                print("result",result.usage.prompt_tokens,result.usage.completion_tokens)
                return structured_response,result.usage.prompt_tokens,result.usage.completion_tokens

            elif result.status == "requires_action":
                print("requires_action")
                if result.required_action and result.required_action.submit_tool_outputs:
                    tool_outputs = []
                    for tool_call in result.required_action.submit_tool_outputs.tool_calls:
                        if tool_call.function.name == "format_mcqs":
                            if tool_call.function and tool_call.function.arguments:
                                try:
                                    structured_response = json.loads(tool_call.function.arguments)
                                except json.JSONDecodeError as e:
                                    logger.error(f"Error parsing JSON: {e}")
                            print("structured_response_mcq",structured_response)
                            tool_outputs.append({
                                "tool_call_id": tool_call.id,
                                "output": json.dumps(structured_response)
                            })

                    result = openai_client.beta.threads.runs.submit_tool_outputs(
                        thread_id=thread_id,
                        run_id=run_id,
                        tool_outputs=tool_outputs
                    )
                continue

            elif result.status in ["failed", "cancelled", "expired"]:
                logger.error(f"Run ended with status: {result.status}")
                return None

            time.sleep(1)
        raise TimeoutError("OpenAI response timeout")

async def process_questions(structured_response, metadata, minhash, db,request):
    """Process questions and identify duplicates"""
    duplicate_questions = []
    valid_questions = []
    for question in structured_response["mcq_set"]["questions"]:
        isduplicate,quest = FindDuplicates(question, metadata, minhash, db,request)
        print(isduplicate,"isduplicate")
        print("\n")
        print(quest,"quest")
        if isduplicate:
            valid_questions.append(quest)
        else:
            duplicate_questions.append(question["question"])

    return valid_questions, duplicate_questions

async def process_question_generation_task(request: GenerateQuestionRequestModel, job_id: str,selectedQuestions):
    """
    Worker function to generate questions using OpenAI API and store results in Redis.
    """
    status_key = f"{job_id}:status"
    redis_conn.set(status_key, "in-progress")
    logger.info(f"Job {job_id} started!")
    print(request,selectedQuestions)
    try:
        max_attempts = 3
        current_attempt = 0
        total_input_token = 0
        total_output_token = 0
        all_valid_questions = []
        remaining_count = request.number_of_questions
        duplicate_questions = []
        assistant_id = fetchAssistant(request.technology_name)
        logger.info(f"Found assistant ID: {assistant_id}")
        # Create a thread in OpenAI
        thread_id = create_Thread()
        logger.info(f"Created OpenAI thread with ID: {thread_id}")
        #adding retry approach
        while current_attempt < max_attempts and remaining_count > 0:
             try:
                # Generate prompt
                combine_concept = ", ".join(request.concepts)
                content = (
                    f"Generate {request.number_of_questions} {request.difficulty_level} multiple-choice "
                    f"questions based on the {request.technology_name} Technology and the concepts: {combine_concept}."
                )
                if current_attempt > 0:
                    duplicate_list = "\n".join(f"{i}. {question}" for i, question in enumerate(duplicate_questions, 1))
                    content = (
                        f"I need {remaining_count} new {request.difficulty_level} multiple-choice questions "
                        f"about {request.technology_name} Technology focusing on concepts: {combine_concept}.\n\n"
                        "Here are the duplicate questions to avoid:\n"
                        f"{duplicate_list}\n\n"
                        "Please ensure the new questions:\n"
                        "1. Are substantially different from the duplicates above\n"
                        "2. Cover different aspects of the concepts\n"
                        "3. Use unique phrasing and structure\n"
                        f"\nGenerate exactly {remaining_count} new questions meeting these criteria."
                    )
                logger.info(f"Attempt {current_attempt + 1}: Sending new message to thread {thread_id}")

                create_message(thread_id,content)
                run = run_assistant(thread_id,assistant_id)
                # print("\n","run",run)
                logger.info(f"Created run {run.id} in thread {thread_id}")

                structured_response,input_token,output_token = await generate_questions(thread_id, run.id,60)
                print("structured_response",structured_response)
                if structured_response:
                    total_input_token += input_token
                    total_output_token += output_token
                    metadata = {
                        "technology": structured_response["mcq_set"]["technology"],
                        "difficulty": structured_response["mcq_set"]["difficulty"],
                    }
                    valid_questions, duplicate_questions = await process_questions(
                            structured_response, metadata, minhash, db,request
                        )
                    all_valid_questions.extend(valid_questions)
                    remaining_count = request.number_of_questions - len(all_valid_questions)

                    if remaining_count == 0:
                            all_valid_questions.extend(selectedQuestions)
                            final_response = {
                                    "status":"success",
                                    "technology": structured_response["mcq_set"]["technology"],
                                    "difficulty": structured_response["mcq_set"]["difficulty"],
                                    "total_questions": len(all_valid_questions),
                                    "questions": all_valid_questions
                            }
                            redis_conn.set(job_id, json.dumps(final_response))
                            redis_conn.set(status_key, "completed")
                            logger.info(f"Job {job_id} completed successfully with {len(all_valid_questions)} questions.")
                            track_api_usage(
                            company_id=request.company_Id,
                            input_tokens=total_input_token,
                            output_tokens=total_output_token,
                            attempts=current_attempt + 1,
                            thread_id=thread_id,
                            status="success",
                            errors=None
                        )
                            return final_response
                    elif duplicate_questions:
                        logger.info(
                            f"Found {len(duplicate_questions)} duplicate questions in attempt {current_attempt + 1}. "
                            f"Regenerating {remaining_count} questions in same thread."
                        )
                else:
                   print("No structured response received.",job_id)
                current_attempt += 1
             except TimeoutError as te:
                logger.error(f"Timeout on attempt {current_attempt + 1} in thread {thread_id}: {str(te)}")
                if current_attempt == max_attempts - 1:
                    raise
                continue
             except json.JSONDecodeError as je:
                 print(f"JSONDecodeError: {je}")
                 continue
             except Exception as e:
                logger.error(f"Error on attempt {current_attempt + 1} in thread {thread_id}: {str(e)}")
                if current_attempt == max_attempts - 1:
                    raise
                continue

        if all_valid_questions:
            all_valid_questions.extend(selectedQuestions)
            final_response = {
                    "status":"partial_success",
                    "technology": structured_response["mcq_set"]["technology"],
                    "difficulty": structured_response["mcq_set"]["difficulty"],
                    "total_questions": len(all_valid_questions),
                    "questions": all_valid_questions,
                    "note": "Only partial questions could be generated due to duplicates"
            }
            track_api_usage(
                company_id=request.company_Id,
                input_tokens=total_input_token,
                output_tokens=total_output_token,
                attempts=current_attempt,
                thread_id=thread_id,
                status="partial_success",
                errors=None
            )
            redis_conn.set(job_id, json.dumps(final_response))
            redis_conn.set(status_key, "completed")
            logger.warning(f"Job {job_id} completed partially with {len(all_valid_questions)} questions in thread {thread_id}")
            return final_response

        raise Exception(f"Failed to generate unique questions after {max_attempts} attempts in thread {thread_id}")

    except Exception as e:
        error_message = str(e)
        track_api_usage(
        company_id=request.company_Id,
        input_tokens=total_input_token,
        output_tokens=total_output_token,
        attempts=current_attempt + 1,
        thread_id=thread_id,
        status="failed",
        errors=[error_message],
        )
        logger.error(f"Error processing job {job_id} in thread {thread_id}: {str(e)}")
        redis_conn.set(status_key, "failed")
        raise e

    finally:
        if 'thread_id' in locals():
            try:
                openai_client.beta.threads.delete(thread_id)
                logger.info(f"Completed processing thread {thread_id}")
            except Exception as e:
                logger.error(f"Error cleaning up thread {thread_id}: {str(e)}")

def track_api_usage(company_id: str,
    input_tokens: int,
    output_tokens: int,
    attempts: int,
    thread_id: str,
    status: str = "completed",
    errors: List[str] = None,):
    """
    Logs API usage to MongoDB.
    """
    if errors is None:
     errors = []
    usage_collection = db["question_gen_usage"]
    usage_data = {
        "company_id": company_id,
        "prompt_tokens": input_tokens,
        "output_tokens": output_tokens,
        "attempts": attempts,
        "total_tokens":input_tokens+output_tokens,
        "thread_id":thread_id,
        "status":status,
        "errors":errors,
        "timestamp": time.time(),
    }
    usage_collection.insert_one(usage_data)
    logger.info(f"API usage tracked for company {company_id}.")







