FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY veille ./veille
RUN pip install --no-cache-dir --no-deps .
ENTRYPOINT ["veille"]
CMD ["run"]
