# Development Guidelines — MTG Commander Deck Builder

## Purpose

This document provides guidelines for developers to ensure consistent code quality, documentation accuracy, and reliable builds. **These guidelines are mandatory for all changes and should be referenced in every development session.**

---

## Table of Contents

1. [Code Change Checklist](#code-change-checklist)
2. [Documentation Update Requirements](#documentation-update-requirements)
3. [Build Validation Procedures](#build-validation-procedures)
4. [Error Handling Standards](#error-handling-standards)
5. [Testing Requirements](#testing-requirements)
6. [Code Review Priorities](#code-review-priorities)

---

## Code Change Checklist

**Every code change must follow this checklist before being committed:**

### Before Writing Code
- [ ] Understand the scope: Is this a bug fix, feature addition, or refactor?
- [ ] Check if the change affects startup scripts, paths, or configuration
- [ ] Review related files that might be affected (callers, dependencies, tests)
- [ ] Consider edge cases: What happens with missing files, network errors, timeouts?

### While Writing Code
- [ ] Validate all inputs and file paths (use `Path.exists()` or equivalent)
- [ ] Add explicit error messages (not cryptic tracebacks)
- [ ] Include graceful fallbacks when possible (don't crash on optional features)
- [ ] Use consistent naming conventions (snake_case for functions/variables, CONSTANT_CASE for globals)
- [ ] Add comments for non-obvious logic, especially in image generation and GPU memory management

### After Writing Code
- [ ] Run the change locally and verify it works end-to-end
- [ ] Test with edge cases: empty inputs, missing files, service unavailable
- [ ] Check logs for warnings or unexpected messages
- [ ] Verify backward compatibility (old saves still load, old API calls still work)

---

## Documentation Update Requirements

**Documentation must be updated SIMULTANEOUSLY with code changes—not after.**

### Files That Must Be Updated (by change type):

#### Configuration Changes
- `paths_config.ps1`: If adding new paths or ports
- `STARTUP_GUIDE.md`: If changing startup behavior or order
- `README.md` → "Configuration" section: If adding new settings

#### API Endpoint Changes
- `README.md` → "API Reference": If adding/modifying endpoints
- Server docstrings: Always include in `server.py` route definitions

#### Image Generation Changes
- `README.md` → "Image Generation Pipeline": If changing art generation flow
- `MAINTENANCE.md` → "Art Style Troubleshooting": If adding new presets or LoRAs
- `image_gen.py` docstrings: Update parameter descriptions

#### Startup/Service Changes
- `STARTUP_INSTRUCTIONS.txt`: For user-visible startup procedures
- `STARTUP_GUIDE.md`: For detailed technical explanations
- `MAINTENANCE.md` → "Service Management": For troubleshooting

#### Database/Deck Format Changes
- `README.md` → "Deck Structure": Document new fields
- Comments in `server.py` model definitions: Explain new deck fields
- Migration notes in `MAINTENANCE.md` if old saves need conversion

### Documentation Quality Standards

- **Be specific**: "Edit paths_config.ps1, line 10" is better than "Update config"
- **Include examples**: Show what the correct output looks like
- **Explain why**: Not just "do this", but "this configures the GPU timeout because..."
- **Use consistent formatting**: Match existing markdown style (headers, lists, code blocks)
- **Keep it current**: If documentation contradicts code, code is usually right—update docs

---

## Build Validation Procedures

**After completing a feature or bug fix, validate the full build before marking complete:**

### Level 1: Code Validation
- [ ] All Python syntax is valid (no import errors, undefined names)
- [ ] All PowerShell scripts can be parsed (test: `powershell -NoProfile -File script.ps1` -WhatIf)
- [ ] No hardcoded paths remain (all paths should reference `paths_config.ps1`)

### Level 2: Service Startup Validation
- [ ] Run `START.bat` and verify all three services start (Ollama → ComfyUI → FastAPI)
- [ ] Open browser to `http://localhost:8000` and verify frontend loads
- [ ] Check `server.log` for startup warnings or errors

### Level 3: Feature Validation
Run the specific feature that was changed:
- **For card generation**: Generate a single card with different art styles and verify:
  - Generation completes without crashes
  - Card displays in deck view immediately after generation
  - No VRAM exhaustion (check ComfyUI memory usage stays below 90% of max)
  - Images are generated with correct art style applied

- **For startup**: Run `STOP.bat` then `START.bat` and verify:
  - No stale processes remain (check Task Manager)
  - All ports are properly released
  - Startup completes in expected time (Ollama ~5s, ComfyUI ~30-60s, FastAPI ~5s)

- **For decks/saves**: Generate a deck with 5 commanders, save it, reload browser, verify:
  - All cards load from saved state
  - No cards are missing or corrupted
  - Deck metadata is intact

### Level 4: Error Condition Validation
Test expected failure modes:
- **ComfyUI down**: Kill ComfyUI while server is running, attempt generation, verify graceful error message
- **Invalid paths**: Edit paths_config.ps1 to wrong path, run START.bat, verify clear error message
- **Port conflict**: Run `netstat -ano` to find what's using port 8000, verify `START.bat` kills it properly
- **GPU memory**: Generate 20 cards back-to-back, verify no OOM errors or generation slowdown

---

## Error Handling Standards

**All errors must meet these criteria:**

### 1. User-Friendly Error Messages
❌ Bad:
```
ValueError: ComfyUI not available: ComfyUI is not running at http://127.0.0.1:8188
```

✅ Good:
```
[ERROR] Image generation failed: ComfyUI is not running.
Please ensure ComfyUI has started. If it keeps failing, check:
  - ComfyUI port 8188 is not blocked by another application
  - System has at least 12GB free GPU VRAM
  - CUDA drivers are up to date
```

### 2. Graceful Fallbacks
- If optional feature fails (face conditioning, style detection), skip it and continue
- Don't crash the entire generation if one image fails
- Log the failure for debugging, show friendly message to user

### 3. Logging Standards
- Use consistent log levels: INFO (progress), WARNING (something unexpected but recovered), ERROR (user action needed)
- Include context: which card, which step, what was expected vs. actual
- Never spam the same error repeatedly (log once, count occurrences)

### 4. Timeout Handling
- All network calls must have timeouts (default 5-10 seconds)
- Retry transient failures (network hiccup) 2-3 times with exponential backoff
- Fail fast for permanent errors (wrong port, service not installed)

### 5. Resource Cleanup
- Always clean up resources in finally blocks (close files, release GPU memory)
- On shutdown, gracefully stop all pending operations
- Don't leave orphaned processes running

---

## Testing Requirements

**Before marking a task "complete", the following tests must pass:**

### Functional Tests
- [ ] Feature works as designed with valid inputs
- [ ] Feature handles edge cases (empty, missing, invalid data)
- [ ] No new warnings in startup or runtime logs

### Regression Tests
- [ ] Existing features still work after this change
- [ ] Old saves/decks still load correctly
- [ ] Startup time hasn't degraded significantly

### Integration Tests
- [ ] The changed component works with its callers
- [ ] The changed component works with its dependencies
- [ ] No race conditions with concurrent operations (e.g., multiple cards generating simultaneously)

### Performance Tests
- [ ] Single card generation time is within baseline (~10-35s depending on style)
- [ ] 100-card generation completes without hanging or slowdown
- [ ] Memory usage stays stable (no leaks over 10+ generations)

---

## Code Review Priorities

**When reviewing code changes, prioritize in this order:**

### Priority 1: Correctness (Does it work?)
- Does it accomplish the intended goal?
- Does it handle errors gracefully?
- Does it work with all input variations?

### Priority 2: Safety (Could it break things?)
- Does it modify paths/startup without updating config?
- Does it skip validation that was there before?
- Does it leave resources uncleaned?
- Does it introduce race conditions?

### Priority 3: Clarity (Can others understand it?)
- Are variables named descriptively?
- Is complex logic explained in comments?
- Are error messages helpful?
- Do new functions have docstrings?

### Priority 4: Performance (Is it fast enough?)
- Does it introduce unnecessary loops or calculations?
- Does it cache results appropriately?
- Does it avoid redundant I/O or API calls?

---

## Common Patterns to Avoid

### ❌ Don't Do This

**Pattern 1: Hardcoded Paths**
```python
# BAD
comfy_path = "E:\Games\comfy\ComfyUI\resources\ComfyUI\main.py"
```
**✅ Do This Instead**
```python
# GOOD - Load from centralized config
from pathlib import Path
config = load_config()
comfy_path = Path(config["ComfyMainPy"])
```

**Pattern 2: Ignoring Errors**
```python
# BAD
try:
    response = requests.get(health_url, timeout=2)
except:
    pass  # Silently fails!
```
**✅ Do This Instead**
```python
# GOOD - Log and handle explicitly
try:
    response = requests.get(health_url, timeout=2)
except requests.Timeout:
    logger.error(f"Service at {health_url} not responding after 2s")
    raise ServiceUnavailableError(f"ComfyUI not ready (timeout after 2s)")
except requests.ConnectionError:
    logger.error(f"Cannot connect to {health_url} - service may not be running")
    raise ServiceUnavailableError("ComfyUI not running")
```

**Pattern 3: Mixing Concerns**
```python
# BAD - Image generation, GPU memory, and API response all in one function
def generate_image(prompt):
    # ... 200 lines of code
```
**✅ Do This Instead**
```python
# GOOD - Separate concerns into focused functions
def generate_image(prompt):
    # Coordinates the generation workflow
    
def _prepare_gpu():
    # GPU memory setup
    
def _validate_prompt(prompt):
    # Input validation
    
def _upload_to_comfy(prompt):
    # ComfyUI API call
```

**Pattern 4: No Validation**
```python
# BAD
def save_deck(deck_data):
    file.write(deck_data)  # What if deck_data is corrupted?
```
**✅ Do This Instead**
```python
# GOOD - Validate before committing
def save_deck(deck_data):
    # Validate structure
    if not _is_valid_deck_format(deck_data):
        raise ValueError(f"Invalid deck format: missing required field {_find_missing_field(deck_data)}")
    
    # Write with backup
    backup_path = Path(save_path).with_suffix(".bak")
    if Path(save_path).exists():
        shutil.copy2(save_path, backup_path)
    
    file.write(deck_data)
```

---

## Self-Check for Future Sessions

**Before starting a session, ask yourself:**

1. **Are there any recent error messages in logs?** Check `server.log` and `STARTUP_FAILURES.log` for patterns
2. **Have any dependencies been updated?** Check `requirements.txt` last modified date; pip should pin versions to prevent breaking changes
3. **Is the documentation current?** Spot-check README.md against actual startup behavior
4. **Are there any TODOs in the code?** Search for "TODO", "FIXME", "HACK" and prioritize them

**Always test these critical paths after any change:**
- Full startup: `START.bat` → services ready → browser opens
- Card generation: Generate 1 card → verify it displays and art is correct
- Deck save/load: Generate 5 cards → reload browser → all cards present
- Error recovery: Kill a service → attempt action → graceful error message

---

## Questions? Issues?

If you encounter a situation not covered in these guidelines:
1. Log the issue and what you tried
2. Make a reasonable decision based on the priorities above (correctness > safety > clarity > performance)
3. Document the decision in code comments
4. Add it to these guidelines so future developers benefit
