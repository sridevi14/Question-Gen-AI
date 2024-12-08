# Question Generation AI Server

This repository contains a Question Generation AI server that generates multiple-choice questions based on given technology, concepts, and difficulty level. The server is powered by OpenAI models and utilizes Docker for containerization.

## Prerequisites

- [Docker](https://www.docker.com/get-started)
- [Docker Compose](https://docs.docker.com/compose/install/)

## Setting Up the Project

### Step 1: Clone the Repository


```bash
git clone https://github.com/sridevi14/Question-Gen-AI.git
cd Question-Gen-AI
```
### Step 2: Configure Environment Variables

Create a .env file in the project root directory to store sensitive configuration:

```bash
# Example .env file contents
OPENAI_API_KEY=your_openai_api_key_here
SECRET_KEY=your_secret_key
REDIS_HOST=your_secret_host
REDIS_PORT=your_redis_port
REDIS_PASSWORD=your_redis_password
MONGO_URI=your_mongo_uri

```
### Step 3: Build and Run the Docker Containers

Use Docker Compose to build and run the FastAPI, Redis, and worker services.


```bash
docker-compose up --build
```

This command will:
- Build the FastAPI app container.
- Build the RQ worker container.
- Start the Redis container.

FastAPI will be running on `http://localhost:8000`.


### Step 4: Interacting with the API

Once the server is up and running, you can interact with the available API endpoints.

Important: To make API requests, you need to include an Authorization header in your requests. Here's an example header you need to add:

```bash
{
  "Authorization": "Bearer your_secret_key"
}
```

1. Generate AI Questions
To generate multiple-choice questions, make a POST request to the /generate_ai_question endpoint.

Endpoint:
POST http://localhost:8000/generate_ai_question

Request Body Example:

```bash
{
    "technology_name": "Golang",
    "concepts": [
        "array"
    ],
    "difficulty_level": "easy",
    "number_of_questions": 3,
    "company_Id": "Hyre",
    "strict_question": true
}
```

2. Get Previously Generated Questions
You can fetch previously generated questions using the /get_questions endpoint.

Endpoint:
GET http://localhost:8000/get_questions

Request Parameters Example:
```bash
{
    "job_Id": "8c7ed05d-0520-4596-88d4-32ea75527a0e"
}
```
