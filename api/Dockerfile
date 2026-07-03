FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn[standard] sqlalchemy psycopg2-binary python-dotenv pydantic-settings

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]