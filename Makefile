SHELL := /bin/zsh

.PHONY: up down backend-test frontend-test lint precommit-install

up:
	docker compose up --build

down:
	docker compose down --remove-orphans

backend-test:
	cd backend && .venv/bin/pytest

frontend-test:
	cd frontend && npm run test -- --run

lint:
	cd backend && .venv/bin/python -m compileall app tests
	cd frontend && npm run typecheck

precommit-install:
	pre-commit install
