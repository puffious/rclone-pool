# Contributing to rclonepool

Thank you for considering contributing to rclonepool! This document provides guidelines for development and testing.

## Development Setup

### 1. Clone the Repository

```bash
git clone https://github.com/YOURUSERNAME/rclone-pool.git
cd rclone-pool
```

### 2. Install rclone

```bash
# macOS
brew install rclone

# Linux
curl https://rclone.org/install.sh | sudo bash

# Verify installation
rclone version
```

### 3. No Python Dependencies!

This project uses only Python standard library, so no `pip install` needed.

## Running Tests

### Quick Test Run

```bash
# Run all tests
python tests/run_tests.py

# Run with verbose output
python -m unittest discover -s tests -p 'test_*.py' -v
```

### Individual Test Modules

```bash
# Test chunker
python -m unittest tests.test_chunker

# Test balancer
python -m unittest tests.test_balancer

# Test manifest manager
python -m unittest tests.test_manifest

# Test config
python -m unittest tests.test_config

# Integration tests (requires rclone)
python tests/test_integration.py
```

### Test Structure

```
tests/
├── __init__.py
├── run_tests.py           # Main test runner
├── test_chunker.py        # Unit tests for chunker.py
├── test_balancer.py       # Unit tests for balancer.py
├── test_manifest.py       # Unit tests for manifest.py
├── test_config.py         # Unit tests for config.py
└── test_integration.py    # Integration tests
```

## Code Style

- Follow PEP 8
- Use descriptive variable names
- Add docstrings to functions and classes
- Keep functions focused and small
- Use type hints where helpful

### Check Syntax

```bash
# Compile all Python files to check syntax
python -m py_compile *.py
python -m py_compile tests/*.py
```

## Docker Testing

### Build and Test Locally

```bash
# Build the image
docker build -t rclonepool:test .

# Run it
docker run -d \
  --name rclonepool-test \
  -p 8080:8080 \
  -v $(pwd)/config:/config:ro \
  rclonepool:test

# Check logs
docker logs -f rclonepool-test

# Clean up
docker stop rclonepool-test
docker rm rclonepool-test
```

### Using Docker Compose

```bash
# Start
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

## CI/CD

### GitHub Actions Workflows

The project has two automated workflows:

#### 1. Tests (`test.yml`)
- Runs on: Push to main/develop, Pull Requests
- Python versions: 3.10, 3.11, 3.12
- Checks: Unit tests, Integration tests, Syntax check

#### 2. Docker Build (`docker.yml`)
- Runs on: Push to main, Tags
- Builds: Multi-arch (amd64, arm64)
- Publishes to: GitHub Container Registry (GHCR)

### Running CI Locally

#### Test Workflow Simulation

```bash
# Install rclone
curl https://rclone.org/install.sh | sudo bash

# Run tests
python -m unittest discover -s tests -p 'test_*.py' -v
cd tests && python test_integration.py
```

#### Docker Build Simulation

```bash
# Build for local architecture
docker build -t rclonepool:local .

# Multi-arch build (requires buildx)
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t rclonepool:multi .
```

## Pull Request Guidelines

1. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes**
   - Write tests for new functionality
   - Update documentation if needed
   - Follow existing code style

3. **Test your changes**
   ```bash
   # Run all tests
   python tests/run_tests.py
   
   # Check syntax
   python -m py_compile *.py
   ```

4. **Commit with clear messages**
   ```bash
   git commit -m "feat: add support for XYZ"
   git commit -m "fix: resolve issue with ABC"
   git commit -m "docs: update README with new feature"
   ```

5. **Push and create PR**
   ```bash
   git push origin feature/your-feature-name
   ```
   Then create a Pull Request on GitHub

## Adding New Tests

### Unit Test Template

```python
"""
Tests for new_module.py
"""
import unittest
from new_module import NewClass


class TestNewClass(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures"""
        self.instance = NewClass()
    
    def tearDown(self):
        """Clean up after tests"""
        pass
    
    def test_something(self):
        """Test description"""
        result = self.instance.method()
        self.assertEqual(result, expected_value)


if __name__ == '__main__':
    unittest.main()
```

## Debugging

### Enable Debug Logging

```bash
# Set log level
export LOGLEVEL=DEBUG

# Run with debug output
python rclonepool.py serve --config config.json
```

### VS Code Debugging

Create `.vscode/launch.json`:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: rclonepool serve",
      "type": "python",
      "request": "launch",
      "program": "${workspaceFolder}/rclonepool.py",
      "args": ["serve", "--config", "${workspaceFolder}/config/config.json"],
      "console": "integratedTerminal"
    },
    {
      "name": "Python: Run Tests",
      "type": "python",
      "request": "launch",
      "program": "${workspaceFolder}/tests/run_tests.py",
      "console": "integratedTerminal"
    }
  ]
}
```

## Documentation

### Update Documentation

When adding features:
1. Update [README.md](README.md) with usage examples
2. Update [docs/CONTEXT.md](docs/CONTEXT.md) with technical details
3. Add docstrings to new functions/classes
4. Update [DOCKER.md](DOCKER.md) if Docker-related

### Documentation Standards

- Use clear, concise language
- Provide code examples
- Explain the "why" not just the "how"
- Keep examples up-to-date

## Release Process

1. Update version in code (if versioned)
2. Update CHANGELOG.md (if exists)
3. Create a git tag:
   ```bash
   git tag -a v0.2.0 -m "Release version 0.2.0"
   git push origin v0.2.0
   ```
4. GitHub Actions will automatically build and publish Docker image

## Getting Help

- **Issues**: Open an issue on GitHub
- **Discussions**: Use GitHub Discussions for questions
- **Documentation**: Check [docs/CONTEXT.md](docs/CONTEXT.md) for architecture details

## Code of Conduct

- Be respectful and inclusive
- Focus on constructive feedback
- Help others learn and grow
- Keep discussions technical and professional

Thank you for contributing! 🎉
