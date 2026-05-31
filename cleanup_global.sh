#!/bin/bash
# Remove any global jarvis-cli installations to ensure clean system

echo "🧹 Cleaning up global jarvis-cli installations..."

# Check for global command
if command -v jarvis-cli >/dev/null 2>&1; then
    GLOBAL_LOCATION=$(which jarvis-cli)
    echo "Found global installation: $GLOBAL_LOCATION"
    
    if [[ "$GLOBAL_LOCATION" == "/usr/local/bin/jarvis-cli" ]]; then
        echo "Removing global symlink/script..."
        rm -f /usr/local/bin/jarvis-cli
        echo "✓ Removed global installation"
    else
        echo "⚠️ Global installation at unexpected location: $GLOBAL_LOCATION"
        echo "Manual removal may be needed"
    fi
else
    echo "✓ No global installation found"
fi

# Check pip installations
echo "Checking for pip installations..."
pip3 show jarvis-cli 2>/dev/null && {
    echo "⚠️ Found pip installation, removing..."
    pip3 uninstall jarvis-cli -y
} || echo "✓ No pip installation found"

# Verify cleanup
if command -v jarvis-cli >/dev/null 2>&1; then
    echo "❌ Global installation still exists:"
    which jarvis-cli
    echo "Please remove manually"
    exit 1
else
    echo "✅ System is clean - no global jarvis-cli installations"
fi

echo ""
echo "Now use the safe virtual environment method:"
echo "  ./setup_dev.sh"
echo "  source venv/bin/activate"
echo "  jarvis-cli"