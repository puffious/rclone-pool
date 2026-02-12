.PHONY: test test-unit test-integration lint docker-build docker-run clean help

# Default target
help:
	@echo "rclonepool - Makefile targets:"
	@echo ""
	@echo "  make test             - Run all tests"
	@echo "  make test-unit        - Run unit tests only"
	@echo "  make test-integration - Run integration tests only"
	@echo "  make lint             - Check Python syntax"
	@echo "  make docker-build     - Build Docker image"
	@echo "  make docker-run       - Run Docker container"
	@echo "  make docker-stop      - Stop Docker container"
	@echo "  make clean            - Clean up temp files"
	@echo "  make help             - Show this help message"

# Run all tests
test:
	@echo "Running all tests..."
	python tests/run_tests.py

# Run unit tests only (exclude integration)
test-unit:
	@echo "Running unit tests..."
	python -m unittest discover -s tests -p 'test_*.py' -v --exclude test_integration

# Run integration tests only
test-integration:
	@echo "Running integration tests..."
	python tests/test_integration.py

# Check Python syntax
lint:
	@echo "Checking Python syntax..."
	python -m py_compile *.py
	python -m py_compile tests/*.py
	@echo "Syntax check passed!"

# Build Docker image
docker-build:
	@echo "Building Docker image..."
	docker build -t rclonepool:local .

# Run Docker container
docker-run:
	@echo "Starting Docker container..."
	docker run -d \
		--name rclonepool \
		-p 8080:8080 \
		-v $(PWD)/config:/config:ro \
		rclonepool:local
	@echo "Container started. Check logs with: docker logs -f rclonepool"

# Stop Docker container
docker-stop:
	@echo "Stopping Docker container..."
	docker stop rclonepool || true
	docker rm rclonepool || true

# Use docker-compose
docker-compose-up:
	docker-compose up -d

docker-compose-down:
	docker-compose down

# Clean up
clean:
	@echo "Cleaning up..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.log" -delete
	rm -rf .pytest_cache .coverage htmlcov
	@echo "Clean complete!"

# Quick start guide
quickstart:
	@echo "=== rclonepool Quick Start ==="
	@echo ""
	@echo "1. Install rclone: curl https://rclone.org/install.sh | sudo bash"
	@echo "2. Configure remotes: rclone config"
	@echo "3. Initialize rclonepool: python rclonepool.py init"
	@echo "4. Start server: python rclonepool.py serve"
	@echo ""
	@echo "See README.md for detailed instructions"
