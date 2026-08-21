PYTHON := python3.11
UV := uv
DOCKER := docker compose -f infra/docker/docker-compose.yml

.PHONY: setup test lint type-check dev docker-up docker-down clean

## Setup: create venv and install deps with uv
setup:
	cd backend && $(UV) venv --python $(PYTHON) && $(UV) sync --extra dev --extra llm

## Run all unit tests
test:
	cd backend && $(UV) run pytest -m unit --cov --cov-report=term-missing

## Run security probe tests
test-security:
	cd backend && $(UV) run pytest -m security -v

## Run integration tests (needs Docker services running)
test-integration:
	cd backend && $(UV) run pytest -m integration -v

## Run all tests
test-all:
	cd backend && $(UV) run pytest --cov --cov-report=term-missing

## Lint with ruff
lint:
	cd backend && $(UV) run ruff check .

## Lint and fix
lint-fix:
	cd backend && $(UV) run ruff check --fix .

## Type check with mypy
type-check:
	cd backend && $(UV) run mypy app/

## Format
fmt:
	cd backend && $(UV) run ruff format .

## Start backend dev server
dev:
	cd backend && $(UV) run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

## Docker Compose up (PostgreSQL, Redis, Jaeger)
docker-up:
	$(DOCKER) up -d
	@echo "Services: PostgreSQL:5432 Redis:6379 Jaeger:16686"

## Docker Compose down
docker-down:
	$(DOCKER) down

## Docker Compose logs
docker-logs:
	$(DOCKER) logs -f

## Clean
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf backend/.coverage backend/htmlcov

