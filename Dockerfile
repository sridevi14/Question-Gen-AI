FROM python:3.10-slim

# Set the working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files into the container
COPY . /app

# Default command (can be overridden in docker-compose)
CMD ["python", "main.py"]
