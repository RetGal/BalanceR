FROM python:3.11-alpine
LABEL maintainer="retgal"

# set a directory for the app
WORKDIR /opt/balancer

ENV BALANCER_CONFIG "/opt/data/config"

# create a volume for the app
VOLUME /opt/data

COPY balancer.py requirements.txt ./
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

CMD ["python", "./balancer.py", "${BALANCER_CONFIG}", "-nolog"]