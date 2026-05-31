# 🔒 Safe Development Setup

## ⚠️ **Protecting System Packages**

Jarvis CLI uses a **virtual environment** approach to avoid conflicts with system Python packages.

## 🧹 **First Time Setup**

```bash
# Clean any existing global installations
./cleanup_global.sh

# Set up safe development environment
./setup_dev.sh
```

## 🚀 **Quick Start**

```bash
# One-time setup (creates isolated environment)
./setup_dev.sh

# Daily usage
source venv/bin/activate   # Enter safe environment
jarvis-cli                 # Use the CLI
deactivate                 # Exit when done
```

## 📦 **Package Isolation**

### ✅ **What we do (SAFE):**
- Create dedicated virtual environment (`venv/`)
- Install dependencies only in venv  
- Use `pip install -e .` (editable/development mode)
- Keep system Python untouched

### ❌ **What we avoid (RISKY):**
- Global `pip install` without venv
- `sudo pip install` (never!)
- Modifying system Python packages
- Installing conflicting dependencies

## 🛡️ **System Safety Features**

### **Automatic Detection:**
```bash
# Script checks if you're in venv
if [[ "$VIRTUAL_ENV" != "" ]]; then
    echo "✓ Safe to proceed"
else
    echo "⚠️ Creating safe environment..."
fi
```

### **Isolation Verification:**
```bash
# Check where Python packages go
python3 -c "import sys; print('Virtual env:', sys.prefix != sys.base_prefix)"
# Should show: Virtual env: True

# Check jarvis-cli location  
which jarvis-cli
# Should show: /path/to/jarvis-cli/venv/bin/jarvis-cli
```

## 🔧 **Development Workflow**

### **Daily Development:**
```bash
cd ~/repos/jarvis-cli
source venv/bin/activate
# Make changes to code
jarvis-cli --test          # Test changes
deactivate                 # Clean exit
```

### **Adding Dependencies:**
```bash
source venv/bin/activate
pip install new-package    # Only affects venv
pip freeze > requirements-dev.txt  # Track dependencies
```

### **Clean Reinstall:**
```bash
rm -rf venv/              # Remove old environment
./setup_dev.sh            # Fresh setup
```

## 📋 **Troubleshooting**

### **"Command not found: jarvis-cli"**
```bash
# You're not in the virtual environment
source venv/bin/activate
jarvis-cli --help
```

### **"Import Error: module not found"**
```bash
# Dependencies missing or wrong environment
source venv/bin/activate
pip install -e .          # Reinstall in editable mode
```

### **"Permission denied"**
```bash
# Never use sudo with virtual environments
# Instead, recreate the environment:
rm -rf venv/
./setup_dev.sh
```

## 🎯 **Best Practices**

1. **Always use virtual environment** for development
2. **Never install globally** unless absolutely necessary  
3. **Test in clean environment** before releasing
4. **Document dependencies** in `pyproject.toml`
5. **Use editable installs** (`pip install -e .`) for development

This ensures jarvis-cli development is **completely isolated** from your system packages! 🛡️