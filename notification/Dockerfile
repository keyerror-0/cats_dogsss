FROM ikxxx/notification-base:latest

WORKDIR /app
COPY . .
COPY wait-for.sh /wait-for.sh
RUN chmod +x /wait-for.sh

CMD ["python", "notification.py"]