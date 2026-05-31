#!/bin/bash
# Safe development setup for jarvis-cli
# Creates virtual environment to avoid breaking system packages

set -e

echo "🔒 Setting up safe jarvis-cli development environment..."

# Check if we're already in a virtual environment
if [[ "$VIRTUAL_ENV" != "" ]]; then
    echo "✓ Already in virtual environment: $VIRTUAL_ENV"
else
    echo "📦 Creating virtual environment..."
    
    # Create venv if it doesn't exist
    if [[ ! -d "venv" ]]; then
        python3 -m venv venv
        echo "✓ Created virtual environment"
    fi
    
    # Activate the virtual environment
    source venv/bin/activate
    echo "✓ Activated virtual environment: $(which python3)"
fi

# Upgrade pip to latest
echo "⬆️ Upgrading pip..."
python3 -m pip install --upgrade pip

# Install jarvis-cli in development mode (editable)
echo "📦 Installing jarvis-cli in development mode..."
pip3 install -e .

# Verify installation
echo "✅ Verifying installation..."
which jarvis-cli
jarvis-cli --help > /dev/null && echo "✓ jarvis-cli command works"

echo ""
echo "🎉 Safe development setup complete!"
echo ""
echo "To use jarvis-cli safely:"
echo "  source venv/bin/activate  # Activate virtual environment"
echo "  jarvis-cli                # Run the CLI"
echo "  deactivate                # When done, leave virtual environment"
echo ""
echo "This isolates jarvis-cli from your system Python packages."