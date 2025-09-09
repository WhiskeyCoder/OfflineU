# set base image (host OS)
FROM python:3.13.5-slim-bookworm

# set the working directory in the container
WORKDIR /app

# copy the dependencies file to the working directory
COPY requirements.txt .

# install dependencies
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# copy the content of the local src directory to the working directory
COPY . .

EXPOSE 5000

# add healthcheck using Python standard library
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health').read()"

# command to run on container start
CMD [ "python", "/app/offlineu_core.py" ] 
