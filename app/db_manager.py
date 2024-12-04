from pymongo import MongoClient,errors
import redis

import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
if not MONGO_URI:
    raise ValueError("MONGO_URI is missing from environment variables.")
_client = None

def get_mongo_connection():
    global _client
    try:
        if _client is None:
            _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            _client.admin.command('ping')
            print("MongoDB connected")
        return _client["hyreV3"]
    except errors.PyMongoError:
        print("Error: Unable to connect to MongoDB.")
        return None




REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")

# Check if required environment variables are set
if not REDIS_HOST:
    raise ValueError("REDIS_HOST is missing from environment variables.")
if not REDIS_PORT:
    raise ValueError("REDIS_PORT is missing from environment variables.")
if not REDIS_PASSWORD:
    raise ValueError("REDIS_PASSWORD is missing from environment variables.")
_redis_client = None

def get_redis_connection():
    global _redis_client
    try:
        if _redis_client is None:
            _redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0,password=REDIS_PASSWORD)
            _redis_client.ping()
            print("Redis connected")
        return _redis_client
    except redis.ConnectionError:
        print("Error: Unable to connect to Redis.")
        return None