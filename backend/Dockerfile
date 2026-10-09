FROM python:3.13-slim
WORKDIR /app/backend
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app
COPY tests/ ./tests
# 生产镜像内含代码；开发环境用 volume 挂载覆盖
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
