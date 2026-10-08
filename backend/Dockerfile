FROM python:3.13-slim
WORKDIR /app/backend
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# 代码通过 volume 挂载（开发模式）；生产可 COPY app/ ./app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
