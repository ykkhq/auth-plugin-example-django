FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 3333

CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py seed_demo && python manage.py collectstatic --noinput && gunicorn inventory_management.wsgi:application --bind 0.0.0.0:3333 --workers 3 --access-logfile - --error-logfile -"]
