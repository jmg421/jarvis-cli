# Multiline Input Guide

Jarvis CLI now supports multiple ways to input multiline content:

## 🎯 **Direct Paste** (Recommended)
Just paste your multiline content directly. The CLI will automatically detect when input contains newlines.

```
❯ line 1
  line 2  
  line 3
```
→ CLI detects: `(detected multiline paste: 3 lines)`

## 📝 **Triple Quote Mode**
Start with `"""`, `'''`, or ``` to enter explicit multiline mode:

```
❯ """
… This is line 1
… This is line 2  
… This is line 3
… """
```
→ CLI shows: `(multi-line mode, end with """)`

## 🔗 **Line Continuation**  
Use trailing backslash `\` to continue on next line:

```
❯ This is a very long line that \
… continues on the next line \
… and keeps going
```

## 📄 **Empty Line Mode**
Start with empty line (just press Enter) to begin multiline input:

```
❯ [press Enter]
… Line 1
… Line 2
… Line 3
… [press Enter again to finish]
```

## 💡 **Tips**

- **Pasting code**: Direct paste works best for code snippets
- **Writing docs**: Triple quote mode for structured text
- **Long commands**: Backslash continuation for shell commands  
- **Interactive mode**: Empty line mode for step-by-step input

## 🚀 **Examples**

### Paste Python Code
```python
❯ def hello_world():
    print("Hello from Jarvis CLI!")
    return "success"

hello_world()
```

### Use Triple Quotes for Markdown
```
❯ """
# My Document
This is **bold** text.
- Item 1
- Item 2
"""
```

### Line Continuation for Commands
```
❯ jarvis-cli --enqueue "process this file" \
… --verbose \
… --output results.json
```

The multiline input system is now robust and handles all common use cases for development workflows!