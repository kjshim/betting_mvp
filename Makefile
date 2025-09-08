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

# CLI shortcuts
cli:
	python -m cli.main $(ARGS)

cli-docker:
	docker-compose exec api python -m cli.main $(ARGS)

# Common operations
open-round:
	python -m cli.main open-round --code $(shell date +%Y%m%d)

lock-round:
	python -m cli.main lock-round --code $(shell date +%Y%m%d)

settle-round:
	python -m cli.main settle-round --code $(shell date +%Y%m%d) --result AUTO

betting-tvl:
	python -m cli.main tvl