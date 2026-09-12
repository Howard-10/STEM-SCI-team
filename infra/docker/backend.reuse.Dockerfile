FROM compose-backend:latest

WORKDIR /app/backend

COPY backend/pyproject.toml backend/README.md ./
COPY backend/src ./src
COPY data/catalogs ./../data/catalogs
COPY data/derived ./../data/derived
COPY data/structured ./../data/structured

RUN python -m pip install --no-cache-dir --no-deps .

CMD ["uvicorn", "stem_sci.main:app", "--host", "0.0.0.0", "--port", "8000"]
