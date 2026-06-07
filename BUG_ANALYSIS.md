# 🐛 JARVIS-CLI BUG ANALYSIS

**Date:** June 4, 2025  
**Method:** Debugging Best Practices + Quantum Bug Hunter Approach  
**Status:** Analysis Complete, Awaiting User Input for Specific Issues

---

## 📊 TEST COVERAGE ANALYSIS

### Python Tests (Backend):
- **73/73 passing** (100% pass rate)
- **Coverage:** File ops, Git ops, Queue, Dashboard, Daemon
- **Gap:** No terminal/TUI tests

### Rust Tests (CLI):
- **2/2 passing** (100% pass rate)  
- **Coverage:** Only SSE timestamp formatting
- **Gap:** **0 tests for terminal rendering, input handling, state management**

### **CRITICAL GAP:**

```
Lines of Rust Code Touching Terminal: ~800 lines (render.rs + tui.rs)
Lines of Rust Tests for Terminal: 0 lines

Test Coverage: 0%
```

**This is a red flag.** The most complex, bug-prone part of the codebase (terminal state management) has **zero automated tests**.

---

## 🔍 CODE ARCHAEOLOGY FINDINGS

### Git History Pattern Analysis:

```bash
$ git log --oneline --grep="fix" -20 | grep -E "render|term|tui|scroll|stair"

178d8ef fix(render): use CR+LF in raw mode to prevent staircase rendering
95a8443 fix: scope raw mode to read_input + streaming only — fix staircase banner
7104b66 fix: eliminate crossterm event queue race between key_watcher and drain
8a413c2 fix: Esc/Ctrl-C interrupt during streaming — address all 4 root causes
2ae076f fix: Esc/Ctrl-C correctly interrupts thinking display (no render race)
3d63cce fix(tui): clear wrapped input lines on redraw to prevent prompt ghost
```

### **"Fallback Layer Trap" Detected**

Per `debugging_best_practices.md`:
> "A bug gets 'fixed' 3+ times, each fix adding another fallback/retry layer"

**Evidence:** 6 consecutive commits fixing terminal rendering issues in the last 10 commits.

**Root Cause:** Missing architectural abstraction (terminal state machine).

---

## 🔴 IDENTIFIED ARCHITECTURAL ISSUES

### 1. **Global Mutable State via AtomicBool**

**Location:** `src/render.rs:6-7`

```rust
static IN_TEXT: AtomicBool = AtomicBool::new(false);
static IN_THINKING: AtomicBool = AtomicBool::new(false);
```

**Problem:**
- State managed via global flags
- No ownership model
- Implicit state machine
- Race conditions possible

**Symptoms:**
- Overlapping text/thinking blocks
- Ghost prompts
- Rendering corruption

### 2. **Thread Detachment Instead of Joining**

**Location:** `src/render.rs:44-60`

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
- Detached threads continue running for up to 80ms
- Multiple spinners can overlap during rapid operations
- Stdout corruption if new output starts before spinner clears
- **This is the "leaf in the gravel" pattern** — hiding the problem (blocking on join) rather than fixing it (async cancellation)

**Risk Level:** HIGH — can cause rendering corruption

### 3. **Raw Mode Scope Confusion**

**Commits addressing this:**
- `95a8443`: "scope raw mode to read_input + streaming only"
- `178d8ef`: "use CR+LF in raw mode to prevent staircase"

**Problem:**
- Raw mode enabled/disabled multiple times
- Unclear ownership of who controls terminal state
- println! vs println_raw! inconsistency
- Potential for raw mode to leak on panic

**Symptoms:**
- Staircase rendering (LF without CR)
- Terminal left in raw mode after exit
- Shell loses line editing

### 4. **Crossterm Event Queue Race**

**Commit:** `7104b66` — "eliminate crossterm event queue race"

**Problem:**
- Multiple consumers of crossterm event stream
- key_watcher and event drain compete
- No guarantee of mutual exclusion

**Risk Level:** MEDIUM — intermittent input loss

---

## 🎯 SPECIFIC BUG HYPOTHESES

### **"Scrolling Issues" (Reported by User)**

Without specific reproduction steps, likely causes:

#### **Hypothesis A: Long Output Overflow**
- **Cause:** Text exceeds terminal height, no pagination
- **Reproduction:** Long assistant responses
- **Fix:** Implement pager (less) for long output

#### **Hypothesis B: ANSI Cursor Positioning**
- **Cause:** Incorrect cursor escape sequences
- **Reproduction:** Rapid scrolling during streaming
- **Fix:** Use crossterm cursor APIs instead of raw escapes

#### **Hypothesis C: Terminal Size Changes**
- **Cause:** No SIGWINCH handler
- **Reproduction:** Resize terminal during output
- **Fix:** Listen for resize events, redraw

#### **Hypothesis D: Raw Mode Persistence**
- **Cause:** Raw mode not cleaned up on panic/interrupt
- **Reproduction:** Ctrl-C during streaming
- **Fix:** RAII guard with panic handler

---

## 🧪 MISSING TESTS (TO BE ADDED)

### **Terminal State Management:**

```rust
#[test]
fn test_raw_mode_raii_guard() {
    // Ensure raw mode is ALWAYS disabled, even on panic
}

#[test]
fn test_no_overlapping_spinners() {
    // Start spinner, immediately print text → spinner must be stopped first
}

#[test]
fn test_crlf_in_raw_mode() {
    // All output in raw mode uses \r\n, not bare \n
}

#[test]
fn test_crossterm_event_queue_exclusive() {
    // Only one consumer of event stream at a time
}
```

### **Regression Tests for Recent Fixes:**

```rust
#[test]
fn test_no_staircase_rendering() {
    // Regression for 178d8ef
}

#[test]
fn test_esc_interrupts_thinking() {
    // Regression for 2ae076f
}

#[test]
fn test_clear_wrapped_input_lines() {
    // Regression for 3d63cce
}
```

---

## 🏗️ PROPOSED REFACTOR: TerminalManager

### **Design:**

```rust
pub struct TerminalManager {
    mode: TerminalMode,
    active_spinner: Option<SpinnerHandle>,
    stdout: io::Stdout,
}

impl TerminalManager {
    pub fn new() -> Self { /* ... */ }
    
    pub fn enter_raw_mode(&mut self) -> Result<RawModeGuard> {
        // Returns RAII guard that auto-exits raw mode
    }
    
    pub fn print(&mut self, text: &str) -> Result<()> {
        // Auto-stops spinner
        // Auto-converts \n to \r\n if in raw mode
        // Single output path
    }
    
    pub fn start_spinner(&mut self, label: &str) -> Result<()> {
        // Cancellable via stop() or automatic on next print()
    }
}
```

### **Benefits:**

1. **Single source of truth** for terminal state
2. **RAII guards** prevent raw mode leaks
3. **Automatic cleanup** of spinners before text
4. **Testable** — can inject mock stdout
5. **No global state** — explicit ownership

### **Migration Path:**

1. Add TerminalManager alongside existing code
2. Migrate one render path at a time
3. Remove global AtomicBool flags
4. Remove raw println! calls

---

## 📊 QUANTUM BUG HUNTER ANALYSIS

### **Current State:**

**Python Tests:** 73 tests, 0 covering Rust terminal code  
**Rust Tests:** 2 tests, 0 covering terminal rendering

**Quantum Prioritization NOT APPLICABLE** — we have zero tests for the bug-prone code.

### **Recommended Approach:**

**Before quantum prioritization, we need TESTS TO PRIORITIZE.**

1. **Write 20-30 terminal render tests** (TDD)
2. **Run quantum prioritizer** to find minimal high-value subset
3. **Use those tests** to validate refactor

**Cost:** $0 (local simulator) for development, $2.60 (QPU) for final validation

---

## 🚨 RED FLAGS (from debugging_best_practices.md)

### ✅ **We're Falling Into These Traps:**

- ❌ "Let's just catch all exceptions" → Thread detachment instead of fixing blocking
- ❌ "This is a quick fix" → 6 consecutive render "fixes"
- ❌ "We'll come back and fix this properly later" → Global AtomicBool state
- ❌ Multiple files doing the same thing → render.rs + tui.rs overlap

### ✅ **We're Doing These Right:**

- ✅ "Understand the problem first" → This analysis document
- ✅ "Use systematic investigation" → Git history, code review
- ✅ "Don't rush" → Not making random changes

---

## 📋 ACTION PLAN

### **Phase 1: Test Infrastructure (Priority 1)**

**Goal:** Get to measurable coverage

- [ ] Add cargo test for raw mode RAII guard
- [ ] Add cargo test for spinner lifecycle
- [ ] Add cargo test for CRLF in raw mode
- [ ] Add integration test for full TUI session
- [ ] Target: 30+ terminal render tests

**Timeline:** 2-3 days  
**Owner:** Jarvis (autonomous)

### **Phase 2: Refactor (Priority 2)**

**Goal:** Replace implicit state with TerminalManager

- [ ] Design TerminalManager API (RFC doc)
- [ ] Implement TerminalManager
- [ ] Migrate render.rs to TerminalManager
- [ ] Migrate tui.rs to TerminalManager
- [ ] Remove global AtomicBool state

**Timeline:** 1 week  
**Owner:** Jarvis (with user approval of RFC)

### **Phase 3: Quantum Validation (Priority 3)**

**Goal:** Find optimal test subset for CI

- [ ] Run quantum prioritizer on 30+ tests
- [ ] Identify 4-8 critical tests
- [ ] Make those the PR gate tests
- [ ] Full suite runs nightly

**Timeline:** 1 day  
**Cost:** $2.60 (QPU run)  
**Owner:** Jarvis

### **Phase 4: Production Hardening (Priority 4)**

**Goal:** Catch regressions early

- [ ] Add fuzzing for rapid mode switches
- [ ] Add property-based tests for state machine
- [ ] Add panic handler to always disable raw mode
- [ ] Add SIGWINCH handler for terminal resize

**Timeline:** 1 week  
**Owner:** Jarvis

---

## 🎯 IMMEDIATE NEXT STEPS

### **For User:**

**Please provide:**

1. **Specific reproduction steps for "scrolling issues":**
   - What command did you run?
   - What happened vs what should have happened?
   - Can you record a video or take screenshots?

2. **List of "many other bugs":**
   - Beyond scrolling, what else is broken?
   - Priority order?

3. **Environment details:**
   - Terminal emulator? (iTerm2, Alacritty, Terminal.app?)
   - macOS version?
   - jarvis-cli commit hash? (`git rev-parse HEAD`)

### **For Jarvis (Autonomous):**

**I will now:**

1. ✅ Create this analysis document
2. ⏳ Start Phase 1: Write terminal render tests (TDD)
3. ⏳ Use dev_pipeline to branch, test, merge
4. ⏳ Report back when tests are in place

**Estimated time:** 2-3 hours (autonomous work)

---

## 📚 REFERENCES

- `~/MasterPlan/debugging_best_practices.md`
- `~/repos/quantum-bug-hunter/README.md`
- Git history: `git log --oneline --grep="fix" -20`
- Test results: `cargo test` + `pytest tests/`

---

**Status:** ✅ ANALYSIS COMPLETE  
**Next:** 🤖 AUTONOMOUS TEST WRITING (Phase 1) or 📞 AWAIT USER INPUT

