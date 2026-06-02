use std::io::{self, Write};
use std::sync::atomic::{AtomicBool, Ordering};

static IN_TEXT: AtomicBool = AtomicBool::new(false);

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
    if let Some(preview) = input_preview {
        println!("\n  \x1b[33m⚡ {name}\x1b[0m \x1b[2m{preview}\x1b[0m");
    } else {
        println!("\n  \x1b[33m⚡ {name}\x1b[0m");
    }
}

pub fn tool_result(result: &str) {
    let preview = truncate_str(result, 160);
    // Replace newlines with arrows for compact single-line display
    let preview = preview.replace('\n', " ↵ ");
    println!("  \x1b[2m→ {preview}\x1b[0m");
}

/// Render a context management / trimming notice.
pub fn context_management(chars: u64) {
    if IN_TEXT.swap(false, Ordering::Relaxed) {
        println!();
    }
    println!("  \x1b[2m[context trimmed — {chars} chars, oldest tool results elided]\x1b[0m");
}

/// Show that the agent is thinking (before any streamed output arrives).
pub fn thinking() {
    // Only print if we haven't started text yet — avoids clobbering mid-stream
    if !IN_TEXT.load(Ordering::Relaxed) {
        print!("  \x1b[2m● thinking...\x1b[0m");
        io::stdout().flush().ok();
    }
}

/// Clear the thinking indicator (called when first real output arrives).
pub fn clear_thinking() {
    print!("\r\x1b[2K");
    io::stdout().flush().ok();
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
            let flag = if dry { " (dry)" } else { "" };
            Some(format!("'{old}' → '{new}'{flag}"))
        }
        _ => {
            // Generic fallback: show first string-valued key
            for (k, v) in obj {
                if let Some(s) = v.as_str() {
                    return Some(format!("{k}='{}'", truncate(s, 60)));
                }
            }
            None
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_unicode_char_boundary_handling() {
        let test_cases = vec![
            "╭────────────────────────────────────────────────────────╮\n│ Jarvis CLI │\n╰────────────────────────────────────────────────────────╯",
            "This is a normal ASCII string that is very long and should be truncated properly",
            "短い",
            "これは非常に長い日本語のテキストです。このテキストは160文字を超える可能性があり、文字境界の問題を引き起こす可能性があります。",
            "🌟✨🚀💫⭐🌙☀️⚡🔥💯🎯🎨🎭🎪🎊🎉🎈🎁🎀",
        ];
        for s in test_cases {
            let preview = truncate_str(s, 160);
            assert!(std::str::from_utf8(preview.as_bytes()).is_ok());
        }
    }

    #[test]
    fn test_format_tool_input_file_read() {
        let input = json!({"path": "src/main.py", "limit": 50});
        let result = format_tool_input("file_read", &input).unwrap();
        assert!(result.contains("main.py"));
        assert!(result.contains("limit=50"));
    }

    #[test]
    fn test_format_tool_input_execute_bash() {
        let input = json!({"command": "ls -la", "working_dir": "/tmp"});
        let result = format_tool_input("execute_bash", &input).unwrap();
        assert!(result.contains("ls -la"));
        assert!(result.contains("/tmp"));
    }

    #[test]
    fn test_format_tool_input_dev_pipeline() {
        let input = json!({"action": "start", "branch": "feat/new"});
        let result = format_tool_input("dev_pipeline", &input).unwrap();
        assert!(result.contains("start"));
        assert!(result.contains("feat/new"));
    }

    #[test]
    fn test_format_tool_input_synthesize() {
        let q = "A".repeat(100);
        let input = json!({"question": q});
        let result = format_tool_input("synthesize", &input).unwrap();
        assert!(result.len() < 100);
    }

    #[test]
    fn test_format_tool_input_unknown() {
        let input = json!({"foo": "bar"});
        let result = format_tool_input("unknown_tool", &input);
        assert!(result.is_some());
    }

    #[test]
    fn test_truncate_str() {
        assert_eq!(truncate_str("hello", 10), "hello");
        assert_eq!(truncate_str("hello world", 5), "hello…");
        // Emoji — each is 4 bytes; truncate at 4 gives exactly one emoji
        let s = "🚀🌟✨";
        let t = truncate_str(s, 4);
        assert!(t.starts_with('🚀'));
    }
}
