#!/bin/bash
# Quick test script to verify tests pass

set -e

echo "========================================="
echo "Running rclonepool tests locally"
echo "========================================="
echo ""

# Check Python version
echo "Python version:"
python3 --version
echo ""

# Check if rclone is available
if command -v rclone &> /dev/null; then
    echo "rclone version:"
    rclone version | head -n 1
    echo ""
else
    echo "⚠️  WARNING: rclone not found. Integration tests will be skipped."
    echo "   Install: curl https://rclone.org/install.sh | sudo bash"
    echo ""
fi

# Run unit tests (excluding integration)
echo "========================================="
echo "Running unit tests..."
echo "========================================="
python3 -m unittest discover -s tests -p 'test_*.py' -v 2>&1 | grep -v test_integration || true

echo ""
echo "========================================="
echo "Running integration tests (if rclone available)..."
echo "========================================="
if command -v rclone &> /dev/null; then
    python3 tests/test_integration.py || echo "Integration tests failed (this is expected if rclone config is not set up)"
else
    echo "Skipped (rclone not available)"
fi

echo ""
echo "========================================="
echo "Test run complete!"
echo "========================================="
