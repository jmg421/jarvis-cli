use crossterm::{
    event::{self, Event, KeyCode, KeyEvent, KeyModifiers, EnableBracketedPaste, DisableBracketedPaste},
    terminal::{disable_raw_mode, enable_raw_mode},
    execute,
};
use std::fs;
use std::io::{self, Write};
use std::path::PathBuf;
use std::time::Duration;

use crate::{daemon, sse, sse::Usage};

pub fn load_api_key_pub() -> Option<String> { load_api_key() }

fn load_api_key() -> Option<String> {
    let key_file = dirs::home_dir()?.join(".jarvis_cli").join("api_key");
    fs::read_to_string(key_file).ok().map(|s| s.trim().to_string())
}

fn history_file() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".jarvis_cli")
        .join("history")
}

fn load_history() -> Vec<String> {
    fs::read_to_string(history_file())
        .unwrap_or_default()
        .lines()
        .map(|s| s.to_string())
        .collect()
}

fn save_history(history: &[String]) {
    let path = history_file();
    fs::create_dir_all(path.parent().unwrap()).ok();
    // Keep last 500 entries
    let start = history.len().saturating_sub(500);
    fs::write(path, history[start..].join("\n")).ok();
}

fn print_help() {
    println!("\n  \x1b[1;36mJarvis CLI — Commands\x1b[0m");
    println!("  \x1b[2m─────────────────────────────────────────────\x1b[0m");
    println!("  \x1b[33m/new\x1b[0m                   Start a fresh session");
    println!("  \x1b[33m/sessions\x1b[0m              List recent sessions");
    println!("  \x1b[33m/resume <id>\x1b[0m           Resume a session by ID");
    println!("  \x1b[33m/session\x1b[0m               Show current session ID");
    println!("  \x1b[33m/delete [id]\x1b[0m           Delete session (default: current)");
    println!("  \x1b[33m/rewind [N]\x1b[0m            Jump back N turns, continue in new session");
    println!("  \x1b[33m/effort <level>\x1b[0m        Set reasoning effort (low|medium|high|max)");
    println!("  \x1b[33m/transcript\x1b[0m            Open conversation in $PAGER (less)");
    println!("  \x1b[33m/changelog\x1b[0m             Show recent release notes");
    println!("  \x1b[33m/cost\x1b[0m                  Show token usage & estimated cost");
    println!("  \x1b[33m/clear\x1b[0m                 Clear the terminal screen");
    println!("  \x1b[33m/help\x1b[0m                  Show this help");
    println!("  \x1b[33m/quit\x1b[0m  \x1b[2mor Ctrl-C×2\x1b[0m     Exit");
    println!("  \x1b[2m─────────────────────────────────────────────\x1b[0m");
    println!("  \x1b[2mPaste: multi-line content shows preview → Enter to send, Esc to cancel\x1b[0m");
    println!("  \x1b[2mHistory: ↑/↓ arrows to navigate\x1b[0m");
    println!("  \x1b[2mLine editing: Ctrl-A/E (start/end) Ctrl-W (del word) Ctrl-U/K (clear)\x1b[0m\n");
}

/// Effort levels for model reasoning. Mirrors kiro-cli's /effort command.
#[derive(Clone, Debug, PartialEq)]
pub enum EffortLevel {
    Low,
    Medium,
    High,
    Max,
}

impl EffortLevel {
    fn from_str(s: &str) -> Option<Self> {
        match s.trim().to_lowercase().as_str() {
            "low"    => Some(Self::Low),
            "medium" => Some(Self::Medium),
            "high"   => Some(Self::High),
            "max"    => Some(Self::Max),
            _        => None,
        }
    }
    fn label(&self) -> &str {
        match self {
            Self::Low    => "low",
            Self::Medium => "medium",
            Self::High   => "high",
            Self::Max    => "max",
        }
    }
    /// Map to backend budget_tokens hint (approximate Claude extended thinking budget).
    pub fn budget_tokens(&self) -> Option<u32> {
        match self {
            Self::Low    => Some(1_024),
            Self::Medium => Some(4_096),
            Self::High   => Some(10_000),
            Self::Max    => None, // no cap — let the model decide
        }
    }
}

/// One turn in the local transcript (for /rewind and /transcript).
#[derive(Clone)]
struct TurnEntry {
    role: &'static str,  // "user" | "assistant"
    text: String,
}

pub async fn run(url: String, session_id: Option<String>, no_daemon: bool) {
    let mut session_id = session_id;

    // Ensure agent backend is running
    if no_daemon {
        // skip auto-start; just check
        if !daemon::is_running(&url).await {
            println!("  \x1b[33m⚠ Agent not running at {url}\x1b[0m");
            println!("  \x1b[2mStart: cd ~/repos/jarvis-agent && uvicorn jarvis_agent.server:app --port 8100\x1b[0m\n");
        }
    } else if let Err(e) = daemon::ensure_running(&url).await {
        println!("  \x1b[31m✗ {e}\x1b[0m");
        println!("  \x1b[2mStart manually: cd ~/repos/jarvis-agent && uvicorn jarvis_agent.server:app --port 8100\x1b[0m\n");
    }

    let api_key = load_api_key();
    let mut history = load_history();
    let mut cumulative_usage = Usage::default();
    // Per-session transcript (for /rewind and /transcript)
    let mut transcript: Vec<TurnEntry> = Vec::new();
    // Current effort/thinking level
    let mut effort: Option<EffortLevel> = None;

    println!("\n  \x1b[36m╭──────────────────────────────────────────────────╮\x1b[0m");
    println!("  \x1b[36m│\x1b[0m \x1b[1mJarvis CLI\x1b[0m — Rust TUI                          \x1b[36m│\x1b[0m");
    println!("  \x1b[36m│\x1b[0m \x1b[2mintrospect • synthesize • build\x1b[0m                  \x1b[36m│\x1b[0m");
    println!("  \x1b[36m╰──────────────────────────────────────────────────╯\x1b[0m");
    println!("  \x1b[2mBackend: {url}\x1b[0m");
    if let Some(ref sid) = session_id {
        println!("  \x1b[2mResuming session: {sid}\x1b[0m");
    }
    println!("  \x1b[2mType /help for commands. Ctrl-C twice to exit.\x1b[0m");
    println!("  \x1b[2m/effort <low|medium|high|max>  •  /rewind [N]  •  /transcript\x1b[0m\n");

    loop {
        let prompt = match read_input(&history) {
            Some(p) if !p.is_empty() => p,
            Some(_) => continue,
            None => break,
        };

        match prompt.as_str() {
            "/quit" | "/exit" | "/q" => break,

            "/new" => {
                session_id = None;
                println!("  \x1b[2mNew session started.\x1b[0m\n");
                continue;
            }

            "/sessions" => {
                match sse::list_sessions(&url).await {
                    Ok(sessions) if sessions.is_empty() => {
                        println!("  \x1b[2mNo sessions found.\x1b[0m\n");
                    }
                    Ok(sessions) => {
                        println!("\n  \x1b[1;32mRecent sessions:\x1b[0m");
                        for s in &sessions {
                            println!("  {s}");
                        }
                        println!();
                    }
                    Err(e) => println!("  \x1b[31m✗ {e}\x1b[0m\n"),
                }
                continue;
            }

            "/session" => {
                match &session_id {
                    Some(sid) => println!("  \x1b[2mCurrent session: \x1b[36m{sid}\x1b[0m\n"),
                    None => println!("  \x1b[2mNo active session (next message starts one).\x1b[0m\n"),
                }
                continue;
            }

            "/cost" => {
                print_cost(&cumulative_usage);
                continue;
            }

            "/clear" => {
                // ANSI clear screen + move cursor to top
                print!("\x1b[2J\x1b[H");
                io::stdout().flush().ok();
                if let Some(ref sid) = session_id {
                    println!("  \x1b[2mSession: \x1b[36m{sid}\x1b[0m\n");
                }
                continue;
            }

            "/help" => {
                print_help();
                continue;
            }

            "/changelog" => {
                print_changelog();
                continue;
            }

            "/transcript" => {
                if transcript.is_empty() {
                    println!("  \x1b[2mNo conversation yet in this session.\x1b[0m\n");
                } else {
                    open_transcript_in_pager(&transcript);
                }
                continue;
            }

            _ => {}
        }

        // ── /effort <level> ──────────────────────────────────────────────────
        if let Some(rest) = prompt.strip_prefix("/effort") {
            let level_str = rest.trim();
            if level_str.is_empty() {
                let current = effort.as_ref().map(|e| e.label()).unwrap_or("default");
                println!("  \x1b[2mCurrent effort: \x1b[33m{current}\x1b[0m");
                println!("  \x1b[2mUsage: /effort <low|medium|high|max>\x1b[0m\n");
            } else if let Some(e) = EffortLevel::from_str(level_str) {
                let label = e.label().to_string();
                effort = Some(e);
                println!("  \x1b[32m✓\x1b[0m Effort set to \x1b[33m{label}\x1b[0m\n");
            } else {
                println!("  \x1b[31m✗ Unknown effort level: '{level_str}'. Use: low, medium, high, max\x1b[0m\n");
            }
            continue;
        }

        // ── /rewind [N] ──────────────────────────────────────────────────────
        if let Some(rest) = prompt.strip_prefix("/rewind") {
            let n: usize = rest.trim().parse().unwrap_or(1);
            let n = n.max(1);
            if transcript.is_empty() {
                println!("  \x1b[2mNothing to rewind — no turns yet.\x1b[0m\n");
            } else {
                // Count user turns and drop the last N
                let user_turns: Vec<usize> = transcript
                    .iter()
                    .enumerate()
                    .filter(|(_, t)| t.role == "user")
                    .map(|(i, _)| i)
                    .collect();
                let keep = user_turns.len().saturating_sub(n);
                let keep_idx = user_turns.get(keep).copied().unwrap_or(0);
                transcript.truncate(keep_idx);
                // Reset session so next message starts fresh with rewound context
                session_id = None;
                let kept = keep;
                let dropped = user_turns.len().saturating_sub(kept);
                println!("  \x1b[32m↩\x1b[0m Rewound {dropped} turn(s). Session reset — next prompt starts a new session.\n");
                if !transcript.is_empty() {
                    println!("  \x1b[2mLast kept prompt:\x1b[0m");
                    if let Some(last_user) = transcript.iter().rev().find(|t| t.role == "user") {
                        let preview: String = last_user.text.chars().take(120).collect();
                        println!("  \x1b[2m│\x1b[0m {preview}\n");
                    }
                }
            }
            continue;
        }

        // Handle /delete <id> with explicit session id
        if let Some(id) = prompt.strip_prefix("/delete") {
            let id = id.trim().to_string();
            let target = if id.is_empty() {
                session_id.clone()
            } else {
                Some(id)
            };
            match target {
                Some(sid) => {
                    match sse::delete_session(&url, &sid).await {
                        Ok(()) => {
                            println!("  \x1b[32m✓ Deleted session {sid}\x1b[0m\n");
                            if session_id.as_deref() == Some(sid.as_str()) {
                                session_id = None;
                                cumulative_usage = Usage::default();
                            }
                        }
                        Err(e) => println!("  \x1b[31m✗ {e}\x1b[0m\n"),
                    }
                }
                None => println!("  \x1b[33mUsage: /delete [session_id]\x1b[0m\n"),
            }
            continue;
        }

        // Handle /resume <id> — might have a space
        if let Some(id) = prompt.strip_prefix("/resume") {
            let id = id.trim();
            if id.is_empty() {
                println!("  \x1b[33mUsage: /resume <session_id>\x1b[0m\n");
            } else {
                session_id = Some(id.to_string());
                println!("  \x1b[2mResumed session: \x1b[36m{id}\x1b[0m\n");
            }
            continue;
        }

        // Handle !cmd — run shell command directly, no LLM, no spinner
        if prompt.starts_with('!') {
            let cmd = prompt[1..].trim();
            if cmd.starts_with("cd ") || cmd == "cd" {
                // cd is special: change the process working directory
                let dir = cmd.strip_prefix("cd").unwrap_or("").trim();
                let target = if dir.is_empty() {
                    dirs::home_dir().unwrap_or_else(|| std::path::PathBuf::from("."))
                } else if dir.starts_with('~') {
                    let rest = dir.strip_prefix('~').unwrap_or("");
                    let home = dirs::home_dir().unwrap_or_else(|| std::path::PathBuf::from("."));
                    if rest.is_empty() { home } else { home.join(rest.trim_start_matches('/')) }
                } else {
                    std::path::PathBuf::from(dir)
                };
                match std::env::set_current_dir(&target) {
                    Ok(()) => println!("  \x1b[2m{}\x1b[0m\n", target.display()),
                    Err(e) => println!("  \x1b[31m✗ cd: {e}\x1b[0m\n"),
                }
            } else if !cmd.is_empty() {
                let output = std::process::Command::new("sh")
                    .arg("-c")
                    .arg(cmd)
                    .output();
                match output {
                    Ok(out) => {
                        let stdout = String::from_utf8_lossy(&out.stdout);
                        let stderr = String::from_utf8_lossy(&out.stderr);
                        if !stdout.is_empty() {
                            for line in stdout.trim_end_matches('\n').lines() {
                                println!("  {line}");
                            }
                            println!();
                        }
                        if !stderr.is_empty() {
                            for line in stderr.trim_end_matches('\n').lines() {
                                println!("  \x1b[33m{line}\x1b[0m");
                            }
                            println!();
                        }
                        if stdout.is_empty() && stderr.is_empty() {
                            // Command ran but produced no output — just a blank line
                            println!();
                        }
                    }
                    Err(e) => println!("  \x1b[31m✗ {e}\x1b[0m\n"),
                }
            }
            history.push(prompt.clone());
            save_history(&history);
            continue;
        }

        // Add to history (skip slash-commands, already handled above)
        history.push(prompt.clone());
        save_history(&history);

        // Record user turn in transcript
        transcript.push(TurnEntry { role: "user", text: prompt.clone() });

        let budget = effort.as_ref().and_then(|e| e.budget_tokens());

        // ── Esc-to-interrupt ─────────────────────────────────────────────
        //
        // We thread a tokio::sync::watch channel into sse::stream.  When the
        // key-watcher thread sets the watch value to `true`, the stream's
        // internal tokio::select! (on every chunk await) wakes immediately,
        // calls finish_thinking() + finish() from *inside* the loop, and
        // returns Err(CANCELLED).  This avoids all races between the spinner
        // thread cleanup and the cancel branch printing.
        let (cancel_tx, cancel_rx) = tokio::sync::watch::channel(false);

        // Background thread: poll crossterm for Esc or Ctrl-C.
        // `done_flag` is set after stream() returns so the thread self-exits.
        let done_flag = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
        let done_flag2 = done_flag.clone();
        let _key_watcher = std::thread::spawn(move || {
            loop {
                if done_flag2.load(std::sync::atomic::Ordering::Relaxed) {
                    break;
                }
                match event::poll(Duration::from_millis(50)) {
                    Ok(true) => {
                        if let Ok(Event::Key(ke)) = event::read() {
                            let is_cancel = matches!(ke.code, KeyCode::Esc)
                                || matches!(
                                    (ke.code, ke.modifiers),
                                    (KeyCode::Char('c'), KeyModifiers::CONTROL)
                                );
                            if is_cancel {
                                // Signal the stream — it will clean up & return CANCELLED
                                let _ = cancel_tx.send(true);
                                break;
                            }
                        }
                    }
                    _ => {}
                }
            }
        });

        let stream_result = sse::stream(
            &url, &prompt, session_id.as_deref(), api_key.as_deref(), budget, cancel_rx,
        ).await;

        // Signal the key-watcher thread to exit (it may already have)
        done_flag.store(true, std::sync::atomic::Ordering::Relaxed);

        match stream_result {
            Ok((new_session_id, usage, assistant_text)) => {
                // Record assistant reply in transcript
                transcript.push(TurnEntry { role: "assistant", text: assistant_text });

                // Accumulate usage across all turns
                cumulative_usage.input_tokens += usage.input_tokens;
                cumulative_usage.output_tokens += usage.output_tokens;
                cumulative_usage.cache_read_tokens += usage.cache_read_tokens;
                cumulative_usage.cache_write_tokens += usage.cache_write_tokens;

                if !usage.is_empty() {
                    let cost = usage.estimated_cost_usd();
                    let iters = if usage.iterations > 0 {
                        format!("  {}↺", usage.iterations)
                    } else {
                        String::new()
                    };
                    let effort_tag = effort.as_ref().map(|e| format!("  effort:{}", e.label())).unwrap_or_default();
                    println!(
                        "  \x1b[2msession: {new_session_id}  ·  {}↑ {}↓  ~${cost:.4}{iters}{effort_tag}\x1b[0m\n",
                        fmt_tokens(usage.input_tokens),
                        fmt_tokens(usage.output_tokens),
                    );
                } else {
                    println!("  \x1b[2msession: {new_session_id}\x1b[0m\n");
                }
                session_id = Some(new_session_id);
            }
            Err(e) if e == sse::CANCELLED => {
                // Clean cancel — sse::stream already called finish_thinking()+finish()
                // Just print the notice and pop the pending transcript entry.
                println!("  \x1b[2m^interrupted\x1b[0m\n");
                transcript.pop();
            }
            Err(e) => {
                // Real error — pop the pending user turn
                transcript.pop();
                println!("  \x1b[31m✗ {e}\x1b[0m\n");
            }
        }
    }

    println!("\n  \x1b[2mGoodbye.\x1b[0m\n");
}

pub fn fmt_tokens_pub(n: u64) -> String { fmt_tokens(n) }

fn fmt_tokens(n: u64) -> String {
    if n >= 1_000_000 {
        format!("{:.1}M", n as f64 / 1_000_000.0)
    } else if n >= 1_000 {
        format!("{:.1}k", n as f64 / 1_000.0)
    } else {
        n.to_string()
    }
}

fn print_changelog() {
    println!("\n  \x1b[1;36mJarvis CLI — Recent Changes\x1b[0m");
    println!("  \x1b[2m─────────────────────────────────────────────────────────\x1b[0m");
    println!("  \x1b[1;33mNext release\x1b[0m  \x1b[2m(kiro-parity-2025 branch)\x1b[0m");
    println!("  \x1b[32m+\x1b[0m Added \x1b[33m/rewind [N]\x1b[0m  — jump back N turns, continue fresh");
    println!("  \x1b[32m+\x1b[0m Added \x1b[33m/effort <level>\x1b[0m — control reasoning budget");
    println!("    \x1b[2mlevels: low (1k tok) · medium (4k) · high (10k) · max (no cap)\x1b[0m");
    println!("  \x1b[32m+\x1b[0m Added \x1b[33m/transcript\x1b[0m — open session history in $PAGER");
    println!("  \x1b[32m+\x1b[0m Added \x1b[33m/changelog\x1b[0m  — this command");
    println!("  \x1b[32m+\x1b[0m Thinking display: agent reasoning shown in real-time");
    println!("  \x1b[32m+\x1b[0m Effort hint passed to backend as budget_tokens param");
    println!("  \x1b[32m+\x1b[0m Double Ctrl-C required to exit (prevents accidental quit)");
    println!("  \x1b[32m+\x1b[0m Session transcript recorded per-session for /rewind + /transcript");
    println!("  \x1b[32m+\x1b[0m Effort level shown in per-turn usage footer");
    println!();
    println!("  \x1b[1;33mv0.1.0\x1b[0m  \x1b[2m(initial release)\x1b[0m");
    println!("  \x1b[32m+\x1b[0m Interactive TUI with raw-mode input, history, paste preview");
    println!("  \x1b[32m+\x1b[0m Session management: /new, /sessions, /resume, /delete");
    println!("  \x1b[32m+\x1b[0m Cost tracking: /cost, per-turn usage footer");
    println!("  \x1b[32m+\x1b[0m Shell escape: !cmd, !cd");
    println!("  \x1b[32m+\x1b[0m Daemon auto-start and health checking");
    println!("  \x1b[32m+\x1b[0m Non-interactive pipe mode: echo \"task\" | jarvis");
    println!("  \x1b[32m+\x1b[0m Word-wrap-aware cursor for wide terminals");
    println!("  \x1b[2m─────────────────────────────────────────────────────────\x1b[0m\n");
}

fn open_transcript_in_pager(transcript: &[TurnEntry]) {
    // Build the transcript text
    let mut text = String::new();
    text.push_str("Jarvis CLI — Session Transcript\n");
    text.push_str("════════════════════════════════════════\n\n");
    for (i, turn) in transcript.iter().enumerate() {
        let role_label = match turn.role {
            "user"      => "You",
            "assistant" => "Jarvis",
            other       => other,
        };
        text.push_str(&format!("[{}] {}\n", i + 1, role_label));
        text.push_str(&"─".repeat(40));
        text.push('\n');
        text.push_str(&turn.text);
        text.push_str("\n\n");
    }

    // Write to a temp file and open in $PAGER (default: less)
    let tmp = std::env::temp_dir().join("jarvis_transcript.txt");
    if let Err(e) = fs::write(&tmp, &text) {
        println!("  \x1b[31m✗ Failed to write transcript: {e}\x1b[0m\n");
        return;
    }

    let pager = std::env::var("PAGER").unwrap_or_else(|_| "less".to_string());
    // Disable raw mode so the pager works properly
    disable_raw_mode().ok();
    let status = std::process::Command::new(&pager)
        .arg(&tmp)
        .status();
    enable_raw_mode().ok();

    match status {
        Ok(_) => {}
        Err(e) => {
            // Fallback: just print to stdout
            println!("  \x1b[33m⚠ Could not launch '{pager}': {e}\x1b[0m");
            println!("  \x1b[2mTranscript written to: {}\x1b[0m\n", tmp.display());
        }
    }
}

fn print_cost(usage: &Usage) {
    if usage.is_empty() {
        println!("  \x1b[2mNo token usage recorded yet.\x1b[0m\n");
        return;
    }
    let total_cost = usage.estimated_cost_usd();
    println!("\n  \x1b[1;36mToken Usage (session total)\x1b[0m");
    println!("  \x1b[2m─────────────────────────────────────\x1b[0m");
    println!("  Input tokens:         \x1b[33m{}\x1b[0m", fmt_tokens(usage.input_tokens));
    println!("  Output tokens:        \x1b[33m{}\x1b[0m", fmt_tokens(usage.output_tokens));
    if usage.cache_read_tokens > 0 {
        println!("  Cache read tokens:    \x1b[2m{}\x1b[0m", fmt_tokens(usage.cache_read_tokens));
    }
    if usage.cache_write_tokens > 0 {
        println!("  Cache write tokens:   \x1b[2m{}\x1b[0m", fmt_tokens(usage.cache_write_tokens));
    }
    println!("  \x1b[2m─────────────────────────────────────\x1b[0m");
    println!("  Estimated cost:       \x1b[32m~${total_cost:.4}\x1b[0m  \x1b[2m(Claude Sonnet 3.7 rates)\x1b[0m\n");
}

fn read_input(history: &[String]) -> Option<String> {
    print!("  \x1b[32m❯\x1b[0m ");
    io::stdout().flush().ok();

    enable_raw_mode().ok();
    execute!(io::stdout(), EnableBracketedPaste).ok();
    let result = read_input_raw(history);
    execute!(io::stdout(), DisableBracketedPaste).ok();
    disable_raw_mode().ok();

    println!();
    result
}

fn clear_paste_preview(lines_printed: usize) {
    if lines_printed == 0 {
        return;
    }
    for _ in 0..lines_printed {
        print!("\x1b[A\x1b[2K");
    }
    print!("\r");
    io::stdout().flush().ok();
}

fn show_paste_preview(text: &str, buf: &str) -> usize {
    let line_count = text.lines().count();
    // Clear the current (possibly wrapped) input line before showing preview.
    // Use \r\x1b[J (go to col 0, erase to end of screen) so wrapped lines are
    // cleared too — mirrors the same fix in redraw_line.
    print!("\r\x1b[J  \x1b[32m❯\x1b[0m ");
    if !buf.is_empty() {
        print!("{buf} ");
    }
    print!("\x1b[2m({line_count} lines pasted)\x1b[0m\r\n");
    let mut printed = 1;
    for line in text.lines() {
        print!("  \x1b[2m│\x1b[0m {line}\r\n");
        printed += 1;
    }
    print!("  \x1b[2m[Enter] send · [Esc] cancel\x1b[0m");
    io::stdout().flush().ok();
    printed
}

/// The prompt prefix displayed before user input (display columns).
const PROMPT_COLS: usize = 4; // "  ❯ "

/// Query the terminal width, defaulting to 80 if unavailable.
fn terminal_width() -> usize {
    // crossterm's terminal::size() returns (cols, rows)
    crossterm::terminal::size()
        .map(|(cols, _)| cols as usize)
        .unwrap_or(80)
}

/// How many terminal rows does `total_display_cols` columns occupy on a
/// terminal that is `term_width` columns wide?
fn display_rows(total_display_cols: usize, term_width: usize) -> usize {
    if term_width == 0 { return 1; }
    (total_display_cols.saturating_sub(1)) / term_width + 1
}

/// Redraw the input line from scratch given buffer content and cursor position (char index).
/// The prompt is "  ❯ " (PROMPT_COLS display columns).
///
/// When the prompt+buffer wraps across multiple terminal rows we move the
/// cursor back to the very first row before clearing, so that stale wrapped
/// fragments are not left on screen.
fn redraw_line(buf: &str, cursor: usize) {
    let term_w = terminal_width();

    // ── How many rows does the current content occupy? ──────────────────────
    // We count display columns using a simple heuristic: ASCII = 1 col,
    // everything else treated as 1 col (good enough for file-path inputs).
    let buf_display_cols: usize = buf.chars().map(|c| if c.is_ascii() { 1 } else { 2 }).sum();
    let total_cols = PROMPT_COLS + buf_display_cols;
    let rows_used = display_rows(total_cols, term_w).max(1);

    // Move up (rows_used - 1) lines to get back to the first row, then go to
    // column 0.  If we are already on the first row this is a no-op.
    if rows_used > 1 {
        print!("\x1b[{}A", rows_used - 1);
    }

    // Clear from cursor to end of screen (wipes all wrapped rows at once).
    print!("\r\x1b[J");

    // Reprint prompt + full buffer.
    print!("  \x1b[32m❯\x1b[0m {buf}");

    // ── Reposition cursor ────────────────────────────────────────────────────
    // cursor is a char-index into buf.  Compute total display cols from the
    // start of the prompt to the cursor position.
    let cursor_byte = buf
        .char_indices()
        .nth(cursor)
        .map(|(i, _)| i)
        .unwrap_or(buf.len());
    let before_cols: usize = buf[..cursor_byte]
        .chars()
        .map(|c| if c.is_ascii() { 1 } else { 2 })
        .sum();
    let cursor_total_cols = PROMPT_COLS + before_cols;

    // Chars after cursor: how far left must we move on the current row?
    let after_cols: usize = buf[cursor_byte..]
        .chars()
        .map(|c| if c.is_ascii() { 1 } else { 2 })
        .sum();

    // If the whole line (including chars after cursor) wraps, the physical
    // cursor is currently at col (total_cols % term_w) on the last row.
    // We need it at col (cursor_total_cols % term_w) on the row that contains
    // the cursor.
    if after_cols > 0 {
        // rows we need to move up to reach cursor row
        let cursor_row   = (cursor_total_cols.saturating_sub(1)) / term_w;
        let last_row     = (total_cols.saturating_sub(1)) / term_w;
        let rows_up      = last_row.saturating_sub(cursor_row);
        let col_on_row   = cursor_total_cols % term_w;

        if rows_up > 0 {
            print!("\x1b[{}A", rows_up);
        }
        // Go to the correct column on that row.
        // We are currently at col (total_cols % term_w); move left/right.
        let current_col = if rows_up > 0 { term_w } else { total_cols % term_w };
        if col_on_row < current_col {
            print!("\x1b[{}D", current_col - col_on_row);
        } else if col_on_row > current_col {
            print!("\x1b[{}C", col_on_row - current_col);
        }
        // Edge: cursor at column 0 after moving up — \r gets us there cleanly.
        if col_on_row == 0 {
            print!("\r");
        }
    }

    io::stdout().flush().ok();
}

fn read_input_raw(history: &[String]) -> Option<String> {
    let mut buf = String::new();
    // cursor is a char-index (not byte-index) into buf
    let mut cursor: usize = 0;
    let mut ctrl_c_count = 0u8;
    let mut paste_content: Option<String> = None;
    let mut paste_lines_printed: usize = 0;
    let mut hist_idx: usize = history.len();
    let mut saved_buf = String::new();

    // Helper: char count of buf
    let char_count = |s: &str| s.chars().count();

    loop {
        if !event::poll(Duration::from_millis(500)).unwrap_or(false) {
            continue;
        }

        match event::read() {
            Ok(Event::Paste(text)) => {
                let text = text.replace("\r\n", "\n").replace('\r', "\n");
                if !text.contains('\n') {
                    // Insert pasted text at cursor
                    let byte_pos = buf.char_indices().nth(cursor).map(|(i, _)| i).unwrap_or(buf.len());
                    buf.insert_str(byte_pos, &text);
                    cursor += char_count(&text);
                    redraw_line(&buf, cursor);
                } else {
                    paste_lines_printed = show_paste_preview(&text, &buf);
                    paste_content = Some(text);
                }
            }
            Ok(Event::Key(KeyEvent { code, modifiers, .. })) => {
                match (code, modifiers) {
                    // ── Exit / cancel ────────────────────────────────────
                    (KeyCode::Char('c'), KeyModifiers::CONTROL) => {
                        ctrl_c_count += 1;
                        if ctrl_c_count >= 2 {
                            return None;
                        }
                        if paste_content.is_some() {
                            clear_paste_preview(paste_lines_printed);
                            paste_content = None;
                            paste_lines_printed = 0;
                        }
                        buf.clear();
                        cursor = 0;
                        print!("\r\x1b[J\n  \x1b[2m(Ctrl-C again to exit)\x1b[0m\r\n  \x1b[32m❯\x1b[0m ");
                        io::stdout().flush().ok();
                    }

                    // ── Readline: move to start of line ──────────────────
                    (KeyCode::Char('a'), KeyModifiers::CONTROL)
                    | (KeyCode::Home, _) => {
                        if paste_content.is_none() {
                            cursor = 0;
                            redraw_line(&buf, cursor);
                        }
                    }

                    // ── Readline: move to end of line ────────────────────
                    (KeyCode::Char('e'), KeyModifiers::CONTROL)
                    | (KeyCode::End, _) => {
                        if paste_content.is_none() {
                            cursor = char_count(&buf);
                            redraw_line(&buf, cursor);
                        }
                    }

                    // ── Readline: delete from cursor to start ─────────────
                    (KeyCode::Char('u'), KeyModifiers::CONTROL) => {
                        if paste_content.is_none() {
                            let byte_pos = buf.char_indices().nth(cursor).map(|(i,_)| i).unwrap_or(buf.len());
                            buf.drain(..byte_pos);
                            cursor = 0;
                            redraw_line(&buf, cursor);
                        }
                    }

                    // ── Readline: delete word before cursor ───────────────
                    (KeyCode::Char('w'), KeyModifiers::CONTROL) => {
                        if paste_content.is_none() && cursor > 0 {
                            let byte_pos = buf.char_indices().nth(cursor).map(|(i,_)| i).unwrap_or(buf.len());
                            // Find start of previous word (skip spaces, then word chars)
                            let chars_before: Vec<char> = buf[..byte_pos].chars().collect();
                            let mut i = chars_before.len();
                            while i > 0 && chars_before[i - 1] == ' ' { i -= 1; }
                            while i > 0 && chars_before[i - 1] != ' ' { i -= 1; }
                            // i is now char index of word start
                            let new_byte_pos = buf.char_indices().nth(i).map(|(b,_)| b).unwrap_or(0);
                            buf.drain(new_byte_pos..byte_pos);
                            cursor = i;
                            redraw_line(&buf, cursor);
                        }
                    }

                    // ── Readline: delete from cursor to end ───────────────
                    (KeyCode::Char('k'), KeyModifiers::CONTROL) => {
                        if paste_content.is_none() {
                            let byte_pos = buf.char_indices().nth(cursor).map(|(i,_)| i).unwrap_or(buf.len());
                            buf.truncate(byte_pos);
                            redraw_line(&buf, cursor);
                        }
                    }

                    // ── Left arrow: move cursor left ──────────────────────
                    (KeyCode::Left, KeyModifiers::NONE) => {
                        if paste_content.is_none() && cursor > 0 {
                            cursor -= 1;
                            redraw_line(&buf, cursor);
                        }
                    }

                    // ── Ctrl-Left / Alt-Left: jump word left ─────────────
                    (KeyCode::Left, m) if m.intersects(KeyModifiers::CONTROL | KeyModifiers::ALT) => {
                        if paste_content.is_none() && cursor > 0 {
                            let chars: Vec<char> = buf.chars().collect();
                            let mut i = cursor;
                            while i > 0 && chars[i - 1] == ' ' { i -= 1; }
                            while i > 0 && chars[i - 1] != ' ' { i -= 1; }
                            cursor = i;
                            redraw_line(&buf, cursor);
                        }
                    }

                    // ── Right arrow: move cursor right ────────────────────
                    (KeyCode::Right, KeyModifiers::NONE) => {
                        if paste_content.is_none() && cursor < char_count(&buf) {
                            cursor += 1;
                            redraw_line(&buf, cursor);
                        }
                    }

                    // ── Ctrl-Right / Alt-Right: jump word right ──────────
                    (KeyCode::Right, m) if m.intersects(KeyModifiers::CONTROL | KeyModifiers::ALT) => {
                        if paste_content.is_none() {
                            let chars: Vec<char> = buf.chars().collect();
                            let len = chars.len();
                            let mut i = cursor;
                            while i < len && chars[i] != ' ' { i += 1; }
                            while i < len && chars[i] == ' '  { i += 1; }
                            cursor = i;
                            redraw_line(&buf, cursor);
                        }
                    }

                    // ── Up arrow: history prev ────────────────────────────
                    (KeyCode::Up, _) => {
                        if paste_content.is_none() && !history.is_empty() && hist_idx > 0 {
                            if hist_idx == history.len() {
                                saved_buf = buf.clone();
                            }
                            hist_idx -= 1;
                            buf = history[hist_idx].clone();
                            cursor = char_count(&buf);
                            redraw_line(&buf, cursor);
                        }
                    }

                    // ── Down arrow: history next ──────────────────────────
                    (KeyCode::Down, _) => {
                        if paste_content.is_none() && hist_idx < history.len() {
                            hist_idx += 1;
                            buf = if hist_idx == history.len() {
                                saved_buf.clone()
                            } else {
                                history[hist_idx].clone()
                            };
                            cursor = char_count(&buf);
                            redraw_line(&buf, cursor);
                        }
                    }

                    // ── Escape: cancel paste preview ──────────────────────
                    (KeyCode::Esc, _) => {
                        if paste_content.is_some() {
                            clear_paste_preview(paste_lines_printed);
                            paste_content = None;
                            paste_lines_printed = 0;
                            redraw_line(&buf, cursor);
                        }
                    }

                    // ── Enter: submit ─────────────────────────────────────
                    (KeyCode::Enter, _) => {
                        if let Some(text) = paste_content {
                            let combined = if buf.is_empty() {
                                text
                            } else {
                                format!("{buf}\n{text}")
                            };
                            return Some(combined);
                        }
                        if !buf.is_empty() {
                            return Some(buf);
                        }
                    }

                    // ── Backspace: delete char before cursor ──────────────
                    (KeyCode::Backspace, _) => {
                        if paste_content.is_none() && cursor > 0 {
                            let byte_pos = buf.char_indices().nth(cursor).map(|(i,_)| i).unwrap_or(buf.len());
                            // Remove the char before cursor
                            let prev_byte = buf.char_indices().nth(cursor - 1).map(|(i,_)| i).unwrap_or(0);
                            buf.drain(prev_byte..byte_pos);
                            cursor -= 1;
                            redraw_line(&buf, cursor);
                        }
                        ctrl_c_count = 0;
                    }

                    // ── Delete: delete char at cursor ─────────────────────
                    (KeyCode::Delete, _) => {
                        if paste_content.is_none() && cursor < char_count(&buf) {
                            let byte_pos = buf.char_indices().nth(cursor).map(|(i,_)| i).unwrap_or(buf.len());
                            let next_byte = buf[byte_pos..].char_indices().nth(1).map(|(i,_)| byte_pos + i).unwrap_or(buf.len());
                            buf.drain(byte_pos..next_byte);
                            redraw_line(&buf, cursor);
                        }
                        ctrl_c_count = 0;
                    }

                    // ── Regular char: insert at cursor ────────────────────
                    (KeyCode::Char(c), _) => {
                        if paste_content.is_none() {
                            let byte_pos = buf.char_indices().nth(cursor).map(|(i,_)| i).unwrap_or(buf.len());
                            buf.insert(byte_pos, c);
                            cursor += 1;
                            redraw_line(&buf, cursor);
                        }
                        ctrl_c_count = 0;
                    }

                    _ => {}
                }
            }
            Ok(_) => {}
            Err(_) => return None,
        }
    }
}
