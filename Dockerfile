FROM python:3.11-alpine
LABEL maintainer="retgal"

# set a directory for the app
WORKDIR /opt/balancer

ENV BALANCER_CONFIG "/opt/data/config"

# create a volume for the app
VOLUME /opt/data

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY balancer.py ./

CMD python ./balancer.py ${BALANCER_CONFIG} -nolog