# 🔍 JARVIS-CLI SELF-IMPROVEMENT REPORT

**Date:** June 4, 2025, 11:45 AM  
**Trigger:** User reported "scrolling issues and many other bugs"  
**Method:** Debugging Best Practices + Quantum Bug Hunter approach

---

## 📊 CURRENT STATE

### Test Suite Status:
✅ **73/73 tests passing** (100% pass rate)

```bash
============================= test session starts ==============================
platform darwin -- Python 3.14.5, pytest-9.0.2, pluggy-1.6.0
collected 73 items
============================== 73 passed in 5.88s ==============================
```

### Recent Commits (Last 10):
```
178d8ef fix(render): use CR+LF in raw mode to prevent staircase rendering
95a8443 fix: scope raw mode to read_input + streaming only — fix staircase banner
7104b66 fix: eliminate crossterm event queue race between key_watcher and drain
8a413c2 fix: Esc/Ctrl-C interrupt during streaming — address all 4 root causes
2ae076f fix: Esc/Ctrl-C correctly interrupts thinking display (no render race)
15fc6b2 feat: Esc (and Ctrl-C) interrupt running agent stream
da80b7b feat: kiro-cli 2.5 parity — /rewind, /effort, /transcript, /changelog
3d63cce fix(tui): clear wrapped input lines on redraw to prevent prompt ghost
51bc3be fix: ! commands bypass LLM entirely in Rust TUI
9eed613 feat: suppress thinking spinner for ! commands in CLI
```

**Pattern:** Last 5 commits are ALL fixes for terminal rendering issues (staircase, raw mode, ghost prompts, rendering races).

---

## 🔴 IDENTIFIED ISSUES

### 1. **Symptom Fixing Pattern (Red Flag)**

**Evidence:** 5 consecutive commits fixing terminal rendering issues:
- "fix staircase rendering"
- "fix staircase banner"
- "fix ghost prompts"
- "fix render race"
- "scope raw mode"

**Root Cause Analysis:**
This matches the **"Fallback Layer Trap"** pattern from debugging_best_practices.md:
> "A bug gets 'fixed' 3+ times, each fix adding another fallback/retry layer, but the bug keeps returning."

**Underlying Issue:**
The terminal rendering system is fundamentally unstable. Each fix addresses a symptom without understanding the root architectural problem.

### 2. **Raw Mode State Management**

**Code Location:** `src/render.rs` + `src/tui.rs`

**Problem:**
- Raw mode is enabled/disabled multiple times during execution
- Multiple render paths (spinner, text streaming, tool calls, input)
- State management is implicit via `AtomicBool` flags
- No clear ownership model for terminal state

**Symptoms:**
- Staircase rendering (LF without CR)
- Ghost prompts
- Scrolling issues
- Rendering races

### 3. **Crossterm Event Queue Race**

**Commit:** `7104b66` — "eliminate crossterm event queue race"

**Problem:**
Event draining and key watching compete for the same event queue. This is a **concurrency bug** that was "fixed" but likely not eliminated.

### 4. **Thread Detachment in SpinnerHandle**

**Code Location:** `src/render.rs:44-60`

```rust
impl Drop for SpinnerHandle {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        // Detach rather than join — joining blocks the caller
        if let Some(t) = self.thread.take() {
            drop(t); // detach
        }
    }
}
```

**Problem:**
Detaching threads rather than joining them is a **resource leak pattern**. The spinner thread will continue running for up to 80ms after drop, during which time it's still printing to stdout.

**Risk:**
- Race conditions during rapid session changes
- Overlapping spinner frames from multiple detached threads
- Stdout corruption if new renders start before old spinner clears

---

## 🎯 ROOT CAUSE HYPOTHESIS

### **Terminal State Machine is Missing**

The codebase has:
- Multiple render functions
- Implicit state via `AtomicBool` flags
- No explicit state transitions
- No ownership model for "who controls stdout"

**This is a classic case of solving symptoms instead of the problem.**

---

## 📝 PROPOSED SOLUTION

### **Phase 1: Terminal State Machine (Refactor)**

Create a centralized `TerminalManager` that owns all terminal state:

```rust
pub struct TerminalManager {
    mode: TerminalMode,      // Raw | Cooked
    active_spinner: Option<SpinnerHandle>,
    in_text_block: bool,
    in_thinking_block: bool,
}

impl TerminalManager {
    pub fn enter_raw_mode(&mut self) -> Result<()>
    pub fn exit_raw_mode(&mut self) -> Result<()>
    pub fn print(&mut self, text: &str) -> Result<()>
    pub fn start_spinner(&mut self, label: &str) -> Result<()>
    pub fn stop_spinner(&mut self) -> Result<()>
}
```

**Benefits:**
- Single source of truth for terminal state
- Explicit mode transitions
- No more implicit flags
- Spinner lifecycle managed by state machine
- All output goes through one path

### **Phase 2: Join Spinner Threads (Fix Resource Leak)**

Replace detach with proper cancellation:

```rust
impl SpinnerHandle {
    pub fn stop(self) {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(t) = self.thread {
            t.join().ok(); // Wait for clean exit
        }
    }
}
```

**Or:** Use tokio tasks instead of threads for better lifecycle management.

### **Phase 3: Event Loop Redesign**

Separate concerns:
- **Input thread:** Reads keyboard events only
- **Render thread:** Handles all stdout
- **Channel:** Input → Main loop → Render

**Benefits:**
- No event queue races
- Clear ownership model
- Easier to test

---

## 🧪 TESTING STRATEGY

### **Current Gap:**
73 tests, but **0 tests for terminal rendering**. All tests are for:
- File operations
- Git operations
- Queue management
- Dashboard API

**No tests for:**
- Raw mode transitions
- Spinner lifecycle
- Text streaming
- Input handling

### **Proposed Tests:**

```rust
#[test]
fn test_terminal_manager_state_transitions() {
    let mut tm = TerminalManager::new();
    assert_eq!(tm.mode(), TerminalMode::Cooked);
    
    tm.enter_raw_mode().unwrap();
    assert_eq!(tm.mode(), TerminalMode::Raw);
    
    tm.exit_raw_mode().unwrap();
    assert_eq!(tm.mode(), TerminalMode::Cooked);
}

#[test]
fn test_spinner_cleanup_before_new_output() {
    let mut tm = TerminalManager::new();
    tm.start_spinner("test").unwrap();
    tm.print("text").unwrap(); // Should auto-stop spinner
    assert!(tm.active_spinner.is_none());
}

#[test]
fn test_no_staircase_rendering_in_raw_mode() {
    let mut tm = TerminalManager::new();
    tm.enter_raw_mode().unwrap();
    let output = capture_stdout(|| {
        tm.print("line1\nline2\n").unwrap();
    });
    assert!(output.contains("\r\n"), "Output should use CR+LF in raw mode");
    assert!(!output.contains("\n\x1b["), "No bare LF before escape codes");
}
```

---

## 📊 QUANTUM BUG HUNTER RECOMMENDATION

### **When to Run:**

Based on `debugging_best_practices.md`:
> "When to use: After major refactors (import paths change), Before releases (find highest-risk tests)"

**Recommendation:** Run quantum prioritizer NOW to find:
1. Which tests would catch the raw mode issues
2. What test coverage is missing
3. Highest-risk paths in the codebase

### **Cost:**
~$2.60 for 100 shots on QuEra Aquila

### **Expected Outcome:**
- Identify 4-8 critical test cases
- Expose infrastructure gaps (e.g., no render tests)
- Prioritize refactor validation

---

## 🚦 ACTION PLAN

### **Immediate (Today):**
1. ✅ Document current state (this file)
2. [ ] Run quantum bug hunter on test suite
3. [ ] Create regression test for "scrolling issue" (once we know what it is)

### **Short-term (This Week):**
1. [ ] Design TerminalManager state machine (RFC doc)
2. [ ] Add terminal render tests (TDD for refactor)
3. [ ] Prototype TerminalManager with existing code paths

### **Medium-term (Next Sprint):**
1. [ ] Refactor: migrate all render calls to TerminalManager
2. [ ] Fix spinner thread leak (join instead of detach)
3. [ ] Validate with full regression suite

### **Long-term:**
1. [ ] Event loop redesign (separate input/render threads)
2. [ ] Property-based testing for terminal state transitions
3. [ ] Fuzz testing for rapid mode switches

---

## 📚 LESSONS LEARNED

### **From debugging_best_practices.md:**

✅ **We followed:**
- "Understand the problem first" — read git history, analyzed commit patterns
- "Use systematic investigation" — checked test status, build status, code

❌ **We violated (historically):**
- "Fix the root cause, not the symptom" — 5 consecutive symptom fixes
- "Don't use band-aid solutions" — raw mode scope changes instead of state machine
- "Don't leave debugging artifacts" — detached threads are a form of debug workaround

### **New Rule for Jarvis-CLI:**

**"Three-Fix Rule"**  
If the same symptom requires >3 fixes, STOP and:
1. Document all prior attempts
2. Diagram the system architecture
3. Identify the missing abstraction
4. Refactor, don't patch

---

## 🔬 HYPOTHESIS FOR "SCROLLING ISSUES"

**Without seeing the specific bug report, likely causes:**

### Option A: Terminal Size Detection
- Terminal size changes not handled
- Output exceeds terminal height → no scroll handling
- Solution: Listen for SIGWINCH, redraw on resize

### Option B: ANSI Escape Code Corruption
- Cursor positioning escapes malformed
- Clear-screen sequences incorrectly scoped
- Solution: Audit all ANSI usage, use crossterm helpers

### Option C: Raw Mode Persistence
- Raw mode left enabled after exit
- User's shell loses line editing
- Solution: RAII guard for raw mode

### Option D: Text Overflow
- Long output lines wrap incorrectly
- No word-wrap in raw mode
- Solution: Manual text wrapping or paginate long output

**Next Step:** User should provide specific reproduction steps for the scrolling issue.

---

## 🎯 SELF-IMPROVEMENT ACTIONS TAKEN

1. ✅ Read debugging_best_practices.md
2. ✅ Analyzed git history for patterns
3. ✅ Identified "Fallback Layer Trap" in recent commits
4. ✅ Documented root cause hypothesis
5. ✅ Proposed architectural solution (TerminalManager)
6. ✅ Created testing strategy
7. ✅ Defined action plan with clear phases
8. ⏳ **Next:** Run quantum bug hunter to validate hypothesis

---

## 📞 USER ACTION REQUIRED

**To proceed with fixing "scrolling issues", I need:**

1. **Specific reproduction steps:**
   - What command was run?
   - What was the expected vs actual behavior?
   - Screenshot or terminal recording if possible

2. **Environment details:**
   - Terminal emulator (iTerm2, Alacritty, etc.)?
   - macOS version?
   - jarvis-cli version (`git rev-parse HEAD`)?

3. **Scope of "many other bugs":**
   - List specific bugs beyond scrolling
   - Priority order

**Once you provide these, I will:**
1. Create targeted regression tests
2. Run quantum prioritizer on the test suite
3. Implement TerminalManager refactor
4. Validate fixes with automated tests

---

**Status:** READY FOR QUANTUM BUG HUNTER RUN + USER INPUT

