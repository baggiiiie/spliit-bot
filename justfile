build:
    docker build -t spliit-bot .

run:
    docker run -d --env-file .env --name spliit-bot spliit-bot

run-webhook:
    docker run -d --env-file .env -p 8443:8443 --name spliit-bot spliit-bot

stop:
    docker stop spliit-bot && docker rm spliit-bot

logs:
    docker logs -f spliit-bot

restart: stop build run
