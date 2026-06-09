use std::io::{self, Write};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

static IN_TEXT: AtomicBool = AtomicBool::new(false);
/// Whether a thinking block is currently open (started but not yet closed).
static IN_THINKING: AtomicBool = AtomicBool::new(false);

// ── Animated spinner ────────────────────────────────────────────────────────

/// Handle to the background spinner task. Drop to stop it.
pub struct SpinnerHandle {
    stop: Arc<AtomicBool>,
    thread: Option<std::thread::JoinHandle<()>>,
}

impl SpinnerHandle {
    /// Spawn a spinner that keeps printing until dropped.
    /// Shows elapsed time after 5 seconds so user knows it's not frozen.
    pub fn start(label: &str) -> Self {
        let stop = Arc::new(AtomicBool::new(false));
        let stop2 = stop.clone();
        let label = label.to_string();
        let thread = std::thread::spawn(move || {
            let frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];
            let mut i = 0usize;
            let started = std::time::Instant::now();
            while !stop2.load(Ordering::Relaxed) {
                let elapsed = started.elapsed().as_secs();
                if elapsed >= 5 {
                    print!("\r  \x1b[2m{} {} ({}s)\x1b[0m  ", frames[i % frames.len()], label, elapsed);
                } else {
                    print!("\r  \x1b[2m{} {}\x1b[0m  ", frames[i % frames.len()], label);
                }
                io::stdout().flush().ok();
                i += 1;
                std::thread::sleep(Duration::from_millis(80));
            }
            // Clear the spinner line
            print!("\r\x1b[2K");
            io::stdout().flush().ok();
        });
        SpinnerHandle { stop, thread: Some(thread) }
    }
}

impl Drop for SpinnerHandle {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
        // Join with a short timeout — the thread checks the flag every 80ms
        // so it will exit within one tick. Joining prevents output races where
        // the spinner's clear-line escape overlaps with new render output.
        if let Some(t) = self.thread.take() {
            let _ = t.join();
        }
    }
}

// ── Tool elapsed time ───────────────────────────────────────────────────────

/// Records when the most recent tool call started (Unix ms, 0 = none).
static TOOL_START_MS: AtomicU64 = AtomicU64::new(0);

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

// ── CR+LF helpers ───────────────────────────────────────────────────────────
//
// All render output happens while raw mode is active (raw mode is enabled
// before sse::stream() is called and disabled after it returns).  In raw
// mode the OS line discipline is bypassed, so a bare '\n' (LF) moves the
// cursor DOWN but does NOT return it to column 0.  Every line of output
// therefore must use explicit CR+LF ("\r\n") or the output staircases
// to the right.
//
// Use `println_raw!` instead of `println!` and `newline()` instead of `println!()`.

macro_rules! println_raw {
    () => {
        print!("\r\n");
        io::stdout().flush().ok();
    };
    ($fmt:literal) => {
        print!(concat!($fmt, "\r\n"));
        io::stdout().flush().ok();
    };
    ($fmt:literal, $($arg:tt)*) => {
        print!(concat!($fmt, "\r\n"), $($arg)*);
        io::stdout().flush().ok();
    };
}

// ── Public render API ───────────────────────────────────────────────────────

pub fn text_delta(text: &str) {
    if !IN_TEXT.swap(true, Ordering::Relaxed) {
        print!("\r\n  ");
    }
    // Handle newlines: in raw mode we need \r\n, not just \n
    let formatted = text.replace('\n', "\r\n  ");
    print!("{formatted}");
    io::stdout().flush().ok();
}

/// Display a tool call with its name and key input fields.
/// `input_preview` is an optional compact summary of the inputs.
pub fn tool_call(name: &str, input_preview: Option<&str>) {
    if IN_TEXT.swap(false, Ordering::Relaxed) {
        print!("\r\n");
    }
    TOOL_START_MS.store(now_ms(), Ordering::Relaxed);
    if let Some(preview) = input_preview {
        println_raw!("\r\n  \x1b[33m⚡ {}\x1b[0m \x1b[2m{}\x1b[0m", name, preview);
    } else {
        println_raw!("\r\n  \x1b[33m⚡ {}\x1b[0m", name);
    }
}

pub fn tool_result(result: &str) {
    let elapsed = {
        let started = TOOL_START_MS.load(Ordering::Relaxed);
        let now = now_ms();
        if started > 0 && now >= started {
            let ms = now - started;
            TOOL_START_MS.store(0, Ordering::Relaxed);
            if ms >= 1000 {
                format!(" \x1b[2m({:.1}s)\x1b[0m", ms as f64 / 1000.0)
            } else {
                format!(" \x1b[2m({ms}ms)\x1b[0m")
            }
        } else {
            String::new()
        }
    };

    let preview = truncate_str(result, 160);
    // Replace newlines with arrows for compact single-line display
    let preview = preview.replace('\n', " ↵ ");
    println_raw!("  \x1b[2m→ {}\x1b[0m{}", preview, elapsed);
}

/// Render a context management / trimming notice.
pub fn context_management(chars: u64) {
    if IN_TEXT.swap(false, Ordering::Relaxed) {
        print!("\r\n");
    }
    println_raw!("  \x1b[2m[context trimmed — {} chars, oldest tool results elided]\x1b[0m", chars);
}

/// Show iteration progress (agent loop count).
pub fn iteration_progress(current: u64, max: u64) {
    if IN_TEXT.swap(false, Ordering::Relaxed) {
        print!("\r\n");
    }
    println_raw!("  \x1b[2m[iteration {}/{}]\x1b[0m", current, max);
}

/// Show that the agent is thinking (before any streamed output arrives).
/// Returns a SpinnerHandle — drop it to stop the spinner.
pub fn thinking() -> SpinnerHandle {
    SpinnerHandle::start("thinking...")
}

/// Stream a chunk of the agent's internal reasoning (kiro 2.5.0 style thinking display).
/// Renders in dim italic to visually separate from the response text.
pub fn thinking_delta(chunk: &str) {
    if !IN_THINKING.swap(true, Ordering::Relaxed) {
        // Opening line — dim header
        print!("\r\n  \x1b[2m╭─ thinking ──────────────────────────────────────\x1b[0m\r\n");
        print!("  \x1b[2m│\x1b[0m ");
    }
    // Indent continuation lines with dim pipe; use \r\n in raw mode
    let formatted = chunk.replace('\n', "\r\n  \x1b[2m│\x1b[0m ");
    print!("\x1b[2m{formatted}\x1b[0m");
    io::stdout().flush().ok();
}

/// Close an open thinking block (if any).
pub fn finish_thinking() {
    if IN_THINKING.swap(false, Ordering::Relaxed) {
        print!("\r\n");
        println_raw!("  \x1b[2m╰─────────────────────────────────────────────────\x1b[0m");
    }
}

pub fn finish() {
    IN_TEXT.store(false, Ordering::Relaxed);
    print!("\r\n\r\n");
    io::stdout().flush().ok();
}

/// Safely truncate a string to at most `max_bytes` bytes, respecting UTF-8 char boundaries.
/// Appends `…` if the string was cut.
fn truncate_str(s: &str, max_bytes: usize) -> String {
    if s.len() <= max_bytes {
        return s.to_string();
    }
    let mut end = max_bytes;
    while !s.is_char_boundary(end) {
        end -= 1;
    }
    format!("{}…", &s[..end])
}

/// Build a compact one-line summary of tool inputs, mirroring the Python
/// `_format_tool_input` function in `jarvis_cli/main.py`.
pub fn format_tool_input(name: &str, input: &serde_json::Value) -> Option<String> {
    use serde_json::Value;

    let obj = input.as_object()?;

    let str_val = |key: &str| -> Option<String> {
        obj.get(key)?.as_str().map(|s| s.to_string())
    };
    let truncate = |s: &str, n: usize| -> String {
        if s.len() > n {
            format!("{}…", &s[..s.char_indices().take_while(|(i, _)| *i < n).last().map(|(i, _)| i).unwrap_or(0)])
        } else {
            s.to_string()
        }
    };

    match name {
        "file_read" => {
            let path = str_val("path")?;
            let mut out = format!("'{path}'");
            if let Some(Value::Number(n)) = obj.get("offset") { out += &format!(" +{n}"); }
            if let Some(Value::Number(n)) = obj.get("limit")  { out += &format!(" limit={n}"); }
            Some(out)
        }
        "file_write" => {
            let path = str_val("path")?;
            let content = str_val("content").unwrap_or_default();
            let lines = content.lines().count();
            Some(format!("'{path}' ({lines} lines)"))
        }
        "file_patch" => {
            let path = str_val("path")?;
            let old = str_val("old_str").unwrap_or_default();
            Some(format!("'{path}' old='{}'", truncate(&old, 40)))
        }
        "execute_bash" => {
            let cmd = str_val("command")?;
            let cmd = truncate(&cmd, 80);
            if let Some(cwd) = str_val("working_dir") {
                Some(format!("'{cmd}' (in {cwd})"))
            } else {
                Some(format!("'{cmd}'"))
            }
        }
        "list_directory" => {
            let path = str_val("path")?;
            let depth = obj.get("depth").and_then(|v| v.as_u64()).unwrap_or(1);
            Some(format!("'{path}' depth={depth}"))
        }
        "glob_search" => {
            let pat = str_val("pattern")?;
            if let Some(p) = str_val("path") {
                Some(format!("'{pat}' in {p}"))
            } else {
                Some(format!("'{pat}'"))
            }
        }
        "grep_search" => {
            let pat = str_val("pattern")?;
            let path = str_val("path").map(|p| format!(" in {p}")).unwrap_or_default();
            let inc  = str_val("include").map(|i| format!(" [{i}]")).unwrap_or_default();
            Some(format!("'{pat}'{path}{inc}"))
        }
        "semantic_search" => {
            let query = str_val("query")?;
            Some(format!("'{}'", truncate(&query, 60)))
        }
        "web_search" => {
            let q = str_val("query")?;
            Some(format!("'{}'", truncate(&q, 60)))
        }
        "web_fetch" => {
            let url = str_val("url")?;
            Some(format!("'{}'", truncate(&url, 80)))
        }
        "execute_python" => {
            let code = str_val("code").unwrap_or_default();
            let first_line = code.lines().next().unwrap_or("").to_string();
            Some(format!("'{}'", truncate(&first_line, 60)))
        }
        "synthesize" => {
            let q = str_val("question")?;
            Some(format!("'{}'", truncate(&q, 60)))
        }
        "db_query" => {
            let action = str_val("action").unwrap_or_else(|| "query".into());
            if action == "query" {
                let sql = str_val("sql").unwrap_or_default();
                Some(format!("'{}'", truncate(&sql, 60)))
            } else if action == "schema" {
                let table = str_val("table").unwrap_or_default();
                Some(format!("schema '{table}'"))
            } else {
                Some(action)
            }
        }
        "symbol_search" => {
            let name_val = str_val("name")?;
            Some(format!("'{name_val}'"))
        }
        "git" => {
            let args = str_val("args")?;
            Some(format!("'{}'", truncate(&args, 60)))
        }
        "dev_pipeline" => {
            let action = str_val("action").unwrap_or_default();
            let branch = str_val("branch").unwrap_or_default();
            Some(format!("{action} '{branch}'"))
        }
        "clipboard_paste" => {
            let text = str_val("text").unwrap_or_default();
            Some(format!("({} chars)", text.len()))
        }
        "image_analyze" => {
            let prompt = str_val("prompt").unwrap_or_default();
            Some(format!("'{}'", truncate(&prompt, 50)))
        }
        "qpu_submit" => {
            let circuit = str_val("circuit_type").unwrap_or_default();
            let device  = str_val("device").unwrap_or_default();
            Some(format!("{circuit} on {device}"))
        }
        "qpu_poll" => {
            let action = str_val("action").unwrap_or_default();
            let task   = str_val("task_id").map(|t| format!(" {}", truncate(&t, 20))).unwrap_or_default();
            Some(format!("{action}{task}"))
        }
        _ => None,
    }
}
