# Windows Encoding Fix

## Problem
Windows console uses CP1252 encoding by default, which cannot handle Unicode emoji characters. This caused `UnicodeEncodeError` when printing emojis like 🤖, ✅, ❌, etc.

## Solution Implemented

### 1. UTF-8 Encoding Configuration (main.py)
- Added UTF-8 encoding setup at the start of `main.py`
- Reconfigures stdout/stderr to use UTF-8 with error replacement
- Sets `PYTHONIOENCODING` environment variable for subprocesses

```python
if sys.platform == "win32":
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    os.environ['PYTHONIOENCODING'] = 'utf-8'
```

### 2. Emoji Replacement
All emojis have been replaced with ASCII-safe text equivalents:
- 🤖 → `[BOT]`
- ✅ → `[OK]`
- ❌ → `[ERROR]`
- ⚠️ → `[WARN]`
- 💡 → `[INFO]`
- 🔍 → `[CHECK]`
- 🧠 → `[THINK]`
- ⌨️ → `[KEYBOARD]`
- 🧭 → `[NAV]`
- 📊 → `[REPORT]`
- 📈 → `[STATS]`
- 📋 → `[LIST]`
- 🔧 → `[TOOL]`
- 🔄 → `[REFLECT]`
- ⏳ → `[WAIT]`

### 3. Subprocess Encoding (automation_runner.py)
- Added `PYTHONIOENCODING='utf-8'` to subprocess environment on Windows
- Ensures subprocess output is properly encoded

## Prevention Guidelines

### DO:
1. ✅ Use ASCII text labels like `[OK]`, `[ERROR]`, `[WARN]` instead of emojis
2. ✅ Always set UTF-8 encoding at the start of scripts that run on Windows
3. ✅ Use `errors='replace'` when configuring encoding to handle edge cases
4. ✅ Set `PYTHONIOENCODING` environment variable for subprocesses

### DON'T:
1. ❌ Use emoji characters in print statements
2. ❌ Assume console encoding will handle Unicode
3. ❌ Hardcode encoding assumptions

## Testing
- All print statements now work on Windows
- Subprocess output is properly encoded
- No more `UnicodeEncodeError` exceptions

## Future Development
When adding new print statements:
- Use ASCII text labels: `[OK]`, `[ERROR]`, `[WARN]`, `[INFO]`, etc.
- Avoid emoji characters
- Test on Windows if possible

