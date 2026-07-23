FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/          app/
COPY models/       models/
COPY data/         data/
COPY alembic/      alembic/
COPY alembic.ini   alembic.ini
COPY cassettes/    cassettes/
COPY entrypoint.sh entrypoint.sh
RUN chmod +x entrypoint.sh

EXPOSE 8000

CMD ["./entrypoint.sh"]
