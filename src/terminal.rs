//! Terminal state machine — replaces scattered raw mode toggles and global AtomicBools.
//!
//! The terminal can only be in one state at a time:
//!   Normal → RawInput → Normal
//!   Normal → Streaming → Normal
//!
//! RAII guards ensure raw mode is always cleaned up, even on panic.

use crossterm::{
    event::EnableBracketedPaste,
    event::DisableBracketedPaste,
    event::DisableMouseCapture,
    execute,
    terminal::{disable_raw_mode, enable_raw_mode},
};
use std::io::{self};
use std::sync::atomic::{AtomicU8, Ordering};

/// The states the terminal can be in.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum State {
    /// Cooked mode. println! works normally (\n → CR+LF).
    Normal = 0,
    /// Raw mode for line editing. Bracketed paste enabled.
    RawInput = 1,
    /// Raw mode for streaming output. Key watcher active.
    Streaming = 2,
}

impl State {
    fn from_u8(v: u8) -> Self {
        match v {
            1 => Self::RawInput,
            2 => Self::Streaming,
            _ => Self::Normal,
        }
    }
}

/// Global terminal state. Only one transition at a time.
static TERMINAL_STATE: AtomicU8 = AtomicU8::new(0);

/// Query the current terminal state.
pub fn current_state() -> State {
    State::from_u8(TERMINAL_STATE.load(Ordering::Acquire))
}

/// Returns true if terminal is in raw mode (either RawInput or Streaming).
pub fn is_raw() -> bool {
    current_state() != State::Normal
}

// ── RAII Guards ─────────────────────────────────────────────────────────────

/// Guard that enables raw mode + bracketed paste for input.
/// Restores cooked mode on drop.
pub struct RawInputGuard;

impl RawInputGuard {
    /// Enter raw input mode. Returns None if already in a non-Normal state.
    pub fn enter() -> Option<Self> {
        let prev = TERMINAL_STATE.compare_exchange(0, 1, Ordering::AcqRel, Ordering::Acquire);
        if prev.is_err() {
            return None;
        }
        enable_raw_mode().ok();
        execute!(io::stdout(), EnableBracketedPaste, DisableMouseCapture).ok();
        Some(RawInputGuard)
    }
}

impl Drop for RawInputGuard {
    fn drop(&mut self) {
        execute!(io::stdout(), DisableBracketedPaste).ok();
        disable_raw_mode().ok();
        TERMINAL_STATE.store(0, Ordering::Release);
    }
}

/// Guard that enables raw mode for streaming (no bracketed paste).
/// Restores cooked mode on drop.
pub struct StreamingGuard;

impl StreamingGuard {
    /// Enter streaming mode. Returns None if already in a non-Normal state.
    pub fn enter() -> Option<Self> {
        let prev = TERMINAL_STATE.compare_exchange(0, 2, Ordering::AcqRel, Ordering::Acquire);
        if prev.is_err() {
            return None;
        }
        enable_raw_mode().ok();
        Some(StreamingGuard)
    }
}

impl Drop for StreamingGuard {
    fn drop(&mut self) {
        disable_raw_mode().ok();
        TERMINAL_STATE.store(0, Ordering::Release);
    }
}

/// Emergency cleanup — call from panic handler or signal handler.
/// Forces terminal back to Normal regardless of current state.
pub fn force_restore() {
    let _ = execute!(io::stdout(), DisableBracketedPaste);
    let _ = disable_raw_mode();
    TERMINAL_STATE.store(0, Ordering::Release);
}

// ── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    /// Tests must run sequentially because they share global TERMINAL_STATE.
    /// We use a single test with sequential assertions to avoid parallel races.
    #[test]
    fn terminal_state_machine() {
        // Reset
        TERMINAL_STATE.store(0, Ordering::Release);

        // -- Initial state
        assert_eq!(current_state(), State::Normal);
        assert!(!is_raw());

        // -- RawInput guard transitions
        {
            let guard = RawInputGuard::enter();
            assert!(guard.is_some());
            assert_eq!(current_state(), State::RawInput);
            assert!(is_raw());

            // Can't enter streaming while in raw input
            let streaming = StreamingGuard::enter();
            assert!(streaming.is_none());

            // Can't double-enter raw input
            let g2 = RawInputGuard::enter();
            assert!(g2.is_none());
        }
        // After drop, back to Normal
        assert_eq!(current_state(), State::Normal);
        assert!(!is_raw());

        // -- Streaming guard transitions
        {
            let guard = StreamingGuard::enter();
            assert!(guard.is_some());
            assert_eq!(current_state(), State::Streaming);
            assert!(is_raw());

            // Can't enter raw input while streaming
            let input = RawInputGuard::enter();
            assert!(input.is_none());
        }
        assert_eq!(current_state(), State::Normal);

        // -- force_restore from any state
        TERMINAL_STATE.store(2, Ordering::Release);
        force_restore();
        assert_eq!(current_state(), State::Normal);

        // -- State::from_u8 roundtrip
        assert_eq!(State::from_u8(0), State::Normal);
        assert_eq!(State::from_u8(1), State::RawInput);
        assert_eq!(State::from_u8(2), State::Streaming);
        assert_eq!(State::from_u8(255), State::Normal);
    }
}
