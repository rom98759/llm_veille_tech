FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY veille ./veille
RUN pip install --no-cache-dir .
ENTRYPOINT ["veille"]
CMD ["run"]
