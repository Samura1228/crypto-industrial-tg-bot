# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Define environment variable
# These should be overridden by Railway's environment variables
ENV TELEGRAM_TOKEN=""
ENV CRYPTOCOMPARE_API_KEY=""

# Run bot.py when the container launches
CMD ["python", "bot.py"]