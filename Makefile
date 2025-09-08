.PHONY: up down migrate seed test lint format clean

up:
	docker-compose up -d

down:
	docker-compose down

migrate:
	docker-compose exec api alembic upgrade head

seed:
	docker-compose exec api python -m cli.main seed --users 10

test:
	docker-compose exec api pytest tests/ -v

lint:
	ruff check .
	mypy .

format:
	black .
	ruff check --fix .

clean:
	docker-compose down -v
	docker system prune -f

install:
	pip install -r requirements-dev.txt

install-prod:
	pip install -r requirements.txt

test-local:
	pytest tests/ -v

setup-env:
	cp .env.example .env