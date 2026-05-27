.PHONY: frontend-build frontend-dev frontend-rebuild help

help:
	@echo "Myth Forge Build Commands:"
	@echo "  make frontend-build    Build frontend for production (updates dist/)"
	@echo "  make frontend-dev      Start frontend dev server (hot reload on changes)"
	@echo "  make frontend-rebuild  Clean rebuild frontend (dist/)"

frontend-build:
	cd frontend && npm run build

frontend-dev:
	cd frontend && npm run dev

frontend-rebuild:
	cd frontend && rm -rf dist && npm run build

# Alias for brevity
rebuild: frontend-build

dev: frontend-dev

build: frontend-build
