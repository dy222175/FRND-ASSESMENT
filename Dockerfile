# Use official Python base image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Copy project files
COPY requirements.txt requirements.txt

# Install dependencies
RUN pip install -r requirements.txt

COPY . . 

EXPOSE 8000

# Run Django development server
# CMD ["python", "manage.py", "runserver", "0.0.0.0:6000"]

CMD python manage.py runserver 
