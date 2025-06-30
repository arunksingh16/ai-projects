FROM --platform=linux/amd64 python:3.11-slim 

WORKDIR /app

# Install dependencies
COPY requirements.txt ./requirements.txt

RUN  pip3 install --upgrade pip && pip3 install -r requirements.txt

# Copy application code
COPY stChat.py .

# Create empty .env file (actual values will be provided through ECS environment variables)
RUN touch .env

# Expose the port Streamlit will run on
EXPOSE 8501

# Command to run the application
CMD streamlit run stChat.py