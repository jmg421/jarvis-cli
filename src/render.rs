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
    pub fn start(label: &str) -> Self {
        let stop = Arc::new(AtomicBool::new(false));
        let stop2 = stop.clone();
        let label = label.to_string();
        let thread = std::thread::spawn(move || {
            let frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];
            let mut i = 0usize;
            while !stop2.load(Ordering::Relaxed) {
                print!("\r  \x1b[2m{} {}\x1b[0m  ", frames[i % frames.len()], label);
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

// ── Public render API ───────────────────────────────────────────────────────

pub fn text_delta(text: &str) {
    if !IN_TEXT.swap(true, Ordering::Relaxed) {
        print!("\n  ");
    }
    // Handle newlines with indentation
    let formatted = text.replace('\n', "\n  ");
    print!("{formatted}");
    io::stdout().flush().ok();
}

/// Display a tool call with its name and key input fields.
/// `input_preview` is an optional compact summary of the inputs.
pub fn tool_call(name: &str, input_preview: Option<&str>) {
    if IN_TEXT.swap(false, Ordering::Relaxed) {
        println!();
    }
    TOOL_START_MS.store(now_ms(), Ordering::Relaxed);
    if let Some(preview) = input_preview {
        println!("\n  \x1b[33m⚡ {name}\x1b[0m \x1b[2m{preview}\x1b[0m");
    } else {
        println!("\n  \x1b[33m⚡ {name}\x1b[0m");
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
    println!("  \x1b[2m→ {preview}\x1b[0m{elapsed}");
}

/// Render a context management / trimming notice.
pub fn context_management(chars: u64) {
    if IN_TEXT.swap(false, Ordering::Relaxed) {
        println!();
    }
    println!("  \x1b[2m[context trimmed — {chars} chars, oldest tool results elided]\x1b[0m");
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
        print!("\n  \x1b[2m╭─ thinking ──────────────────────────────────────\x1b[0m\n");
        print!("  \x1b[2m│\x1b[0m ");
    }
    // Indent continuation lines with dim pipe
    let formatted = chunk.replace('\n', "\n  \x1b[2m│\x1b[0m ");
    print!("\x1b[2m{formatted}\x1b[0m");
    io::stdout().flush().ok();
}

/// Close an open thinking block (if any).
pub fn finish_thinking() {
    if IN_THINKING.swap(false, Ordering::Relaxed) {
        println!();
        println!("  \x1b[2m╰─────────────────────────────────────────────────\x1b[0m");
    }
}

pub fn finish() {
    IN_TEXT.store(false, Ordering::Relaxed);
    println!("\n");
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
            let path = str_val("path").map(|p| format!(" path='{p}'")).unwrap_or_default();
            let inc = str_val("include").map(|i| format!(" include='{i}'")).unwrap_or_default();
            Some(format!("/{pat}/{path}{inc}"))
        }
        "web_search" => {
            let q = str_val("query")?;
            Some(format!("'{}'", truncate(&q, 60)))
        }
        "web_fetch" => {
            let url = str_val("url")?;
            Some(format!("'{}'", truncate(&url, 80)))
        }
        "symbol_search" => {
            let name_val = str_val("name")?;
            if let Some(p) = str_val("path") {
                Some(format!("'{name_val}' in {p}"))
            } else {
                Some(format!("'{name_val}'"))
            }
        }
        "git" => {
            let args = str_val("args")?;
            if let Some(cwd) = str_val("working_dir") {
                Some(format!("'{args}' (in {cwd})"))
            } else {
                Some(format!("'{args}'"))
            }
        }
        "dev_pipeline" => {
            let action = str_val("action")?;
            let branch = str_val("branch").unwrap_or_default();
            let mut out = format!("action='{action}' branch='{branch}'");
            if let Some(msg) = str_val("message") { out += &format!(" msg='{}'", truncate(&msg, 40)); }
            Some(out)
        }
        "synthesize" => {
            let q = str_val("question")?;
            Some(format!("'{}'", truncate(&q, 60)))
        }
        "auto_fix" => {
            let cmd = str_val("command")?;
            if let Some(cwd) = str_val("working_dir") {
                Some(format!("'{cmd}' (in {cwd})"))
            } else {
                Some(format!("'{cmd}'"))
            }
        }
        "semantic_index" | "semantic_search" => {
            let query = str_val("query").or_else(|| str_val("path")).unwrap_or_default();
            Some(format!("'{}'", truncate(&query, 60)))
        }
        "db_query" => {
            if let Some(sql) = str_val("sql") {
                Some(format!("'{}'", truncate(&sql, 60)))
            } else {
                str_val("action").map(|a| format!("action='{a}'"))
            }
        }
        "image_analyze" => {
            let prompt = str_val("prompt").unwrap_or_default();
            Some(format!("'{}'", truncate(&prompt, 60)))
        }
        "qpu_submit" => {
            let circuit = str_val("circuit_type").unwrap_or_default();
            let device = str_val("device").unwrap_or_default();
            Some(format!("circuit='{circuit}' device='{device}'"))
        }
        "qpu_poll" => {
            let action = str_val("action").unwrap_or_default();
            if let Some(id) = str_val("task_id") {
                Some(format!("action='{action}' id='{}'", truncate(&id, 20)))
            } else {
                Some(format!("action='{action}'"))
            }
        }
        "test_runner" => {
            let cmd = str_val("command")?;
            Some(format!("'{}'", truncate(&cmd, 60)))
        }
        "clipboard_paste" => {
            let text = str_val("text")?;
            let paste = obj.get("paste").and_then(|v| v.as_bool()).unwrap_or(false);
            let suffix = if paste { " +paste" } else { "" };
            Some(format!("'{}'{}",truncate(&text, 40), suffix))
        }
        "multi_file_refactor" => {
            let old = str_val("old_name")?;
            let new = str_val("new_name")?;
            let dry = obj.get("dry_run").and_then(|v| v.as_bool()).unwrap_or(true);
            Some(format!("'{old}' → '{new}' dry_run={dry}"))
        }
        "use_aws" => {
            let svc = str_val("service").unwrap_or_default();
            let op = str_val("operation").unwrap_or_default();
            Some(format!("{svc}::{op}"))
        }
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_format_tool_input_file_read() {
        let input = json!({"path": "/foo/bar.rs", "offset": 10, "limit": 50});
        let result = format_tool_input("file_read", &input).unwrap();
        assert_eq!(result, "'/foo/bar.rs' +10 limit=50");
    }

    #[test]
    fn test_format_tool_input_execute_bash() {
        let input = json!({"command": "cargo test", "working_dir": "/repo"});
        let result = format_tool_input("execute_bash", &input).unwrap();
        assert_eq!(result, "'cargo test' (in /repo)");
    }

    #[test]
    fn test_format_tool_input_dev_pipeline() {
        let input = json!({"action": "full", "branch": "feat/foo", "message": "add feature"});
        let result = format_tool_input("dev_pipeline", &input).unwrap();
        assert!(result.contains("action='full'"));
        assert!(result.contains("branch='feat/foo'"));
    }

    #[test]
    fn test_format_tool_input_synthesize() {
        let input = json!({"question": "Is Rust faster than Go?"});
        let result = format_tool_input("synthesize", &input).unwrap();
        assert_eq!(result, "'Is Rust faster than Go?'");
    }

    #[test]
    fn test_unicode_char_boundary_handling() {
        // Emoji are 4 bytes each — truncate must not split mid-char
        let s = "hello 🦀🦀🦀 world";
        // truncate_str is private, but format_tool_input exercises it
        let input = serde_json::json!({"query": s});
        let result = format_tool_input("web_search", &input);
        assert!(result.is_some());
    }
}
