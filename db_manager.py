from pymongo import MongoClient,errors
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv('MONGO_URI')
if not MONGO_URI:
    raise ValueError("MONGO_URI is missing from environment variables.")
_client = None

def get_db_connection():
    global _client
    try:
        if _client is None:
            _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            print(_client.admin.command('ping'))
            print("MongoDB connected")
        else:
            print("Using existing MongoDB client")
        return _client["hyreV3"]
    except errors.PyMongoError:
        print("Error: Unable to connect to MongoDB.")
        return None