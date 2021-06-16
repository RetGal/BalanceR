FROM python:3
LABEL maintainer="retgal"

# set a directory for the app
WORKDIR /opt/balancer

ENV BALANCE_R_CONFIG "/opt/balancer/test"

# create a volume for the app
VOLUME /opt/data

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

CMD python ./balancer.py ${BALANCE_R_CONFIG} 