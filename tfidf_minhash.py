import hashlib
from sklearn.feature_extraction.text import TfidfVectorizer
from datetime import datetime
import re
import time
import pickle,os
from redis import Redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
redis_conn = Redis(host=REDIS_HOST, port=REDIS_PORT)

# MinHash Class
class MinHash:
    def __init__(self, num_permutations: int = 100):
        self.num_permutations = num_permutations
        self.hash_seeds = list(range(num_permutations))

    def _get_hash(self, item: str, seed: int) -> int:
        hash_obj = hashlib.md5(f"{seed}{item}".encode())
        return int(hash_obj.hexdigest(), 16)

    def get_signature(self, document: set) -> list:
        signature = []
        for seed in self.hash_seeds:
            min_hash = float('inf')
            for item in document:
                hash_value = self._get_hash(item, seed)
                min_hash = min(min_hash, hash_value)
            signature.append(min_hash)
        return signature

    def estimate_similarity(self, sig1: list, sig2: list) -> float:
        matches = sum(1 for i in range(len(sig1)) if sig1[i] == sig2[i])
        return matches / len(sig1)

# Generate unique question hash
def generate_question_hash(question: str, metadata: dict) -> str:
    hash_input = f"{question}:{metadata}"
    return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()

# Preprocessing for questions
def preprocess_question(question: str) -> str:
    question = question.lower()
    question = re.sub(r'[^\w\s]', '', question)
    question = ' '.join(question.split())
    return question

# TF-IDF Similarity
def calculate_tfidf_similarity(question1: str, question2: str) -> float:
    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform([question1, question2])
    cosine_similarity = (tfidf_matrix * tfidf_matrix.T).toarray()[0, 1]
    return cosine_similarity

# Check for duplicate questions
def is_duplicate(question, metadata, minhash: MinHash, db, hash_value):
    # Exact Match (Hash-based)
    exact_match = db["duplicate_find"].find_one({"hash": hash_value})
    if exact_match:
        print("exact duplicate found")
        return True

    # Filter documents by technology and tags
    relevant_docs = db["duplicate_find"].find({
        "metadata.technology": metadata["technology"],
        "metadata.difficulty": metadata["difficulty"],
        "question.tags": {"$in": question["tags"]}
    })

    documents = list(relevant_docs)

    # MinHash Similarity
    shingles = set(preprocess_question(question["question"]).split())
    question_signature = minhash.get_signature(shingles)
    minhash_duplicate_found = False
    for existing in documents:
        # MinHash Comparison
        existing_hash = existing["hash"]
        redis_key = f"question_signature:{existing_hash}"
        stored_signature = redis_conn.get(redis_key)
        if stored_signature:
            existing_signature =  pickle.loads(stored_signature)
            print("Existing Signature found")
        else:
            existing_shingles = set(preprocess_question(existing["question"]["question"]).split())
            existing_signature = minhash.get_signature(existing_shingles)
            redis_conn.set(redis_key, pickle.dumps(existing_signature))
            print("Signature not found in Redis")

        if minhash.estimate_similarity(question_signature, existing_signature) > 0.85:
            minhash_duplicate_found = True
            break
    if(minhash_duplicate_found):
        print("MinHash found duplicate")
        return True
    else:
        print("MinHash didn't find a match, moving to TF-IDF")
    # TF-IDF Similarity
    for existing in documents:
        existing_question = preprocess_question(existing["question"]["question"])
        similarity = calculate_tfidf_similarity(preprocess_question(question["question"]), existing_question)
        print("TF-IDF Similarity",similarity)
        if similarity > 0.85:
            print("TF-IDF found duplicate")
            return True
    redis_key = f"question_signature:{hash_value}"
    redis_conn.set(redis_key, pickle.dumps(question_signature))
    return False


# Store question if not duplicate
def FindDuplicates(question, metadata, minhash:MinHash, db,request):
    hash_value = generate_question_hash(question["question"], metadata)
    if is_duplicate(question, metadata, minhash, db,hash_value):
        print(f"Duplicate found: {question['question']}")
        return False,None
    #updating question ID
    max_question = db["duplicate_find"].find_one(sort=[("question.id", -1)])
    next_question_id = (max_question["question"]["id"] + 1) if max_question else 1
    question["id"] = next_question_id

    question_data = {
        "question": question,
        "hash": hash_value,
        "metadata": metadata,
        "created_at": datetime.now().timestamp(),
        "generated_by": request.company_Id,
        "strict_question":request.strict_question
    }
    db["duplicate_find"].insert_one(question_data)
    print(f"Stored question: {question['question']}")
    return True,question

