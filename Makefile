.PHONY: up down logs test offline-demo secrets
up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f gateway simulator broker

test:
	python -m pytest -q

offline-demo:
	python -m scripts.offline_demo

secrets:
	python scripts/generate_env.py
