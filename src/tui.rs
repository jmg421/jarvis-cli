use crossterm::{
    event::{self, Event, KeyCode, KeyEvent, KeyModifiers, EnableBracketedPaste, DisableBracketedPaste},
    terminal::{disable_raw_mode, enable_raw_mode},
    execute,
};
use std::fs;
use std::io::{self, Write};
use std::path::PathBuf;
use std::time::Duration;

use crate::{daemon, sse};

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
    println!("  \x1b[33m/new\x1b[0m              Start a fresh session");
    println!("  \x1b[33m/sessions\x1b[0m         List recent sessions");
    println!("  \x1b[33m/resume <id>\x1b[0m      Resume a session by ID");
    println!("  \x1b[33m/session\x1b[0m          Show current session ID");
    println!("  \x1b[33m/help\x1b[0m             Show this help");
    println!("  \x1b[33m/quit\x1b[0m  \x1b[2mor Ctrl-C×2\x1b[0m  Exit");
    println!("  \x1b[2m─────────────────────────────────────────────\x1b[0m");
    println!("  \x1b[2mPaste: multi-line content shows preview → Enter to send, Esc to cancel\x1b[0m");
    println!("  \x1b[2mHistory: ↑/↓ arrows to navigate\x1b[0m\n");
}

pub async fn run(url: String, session_id: Option<String>) {
    let mut session_id = session_id;

    // Ensure agent backend is running
    if let Err(e) = daemon::ensure_running(&url).await {
        println!("  \x1b[31m✗ {e}\x1b[0m");
        println!("  \x1b[2mStart manually: cd ~/repos/jarvis-agent && uvicorn jarvis_agent.server:app --port 8100\x1b[0m\n");
    }

    let api_key = load_api_key();
    let mut history = load_history();

    println!("\n  \x1b[36m╭──────────────────────────────────────────────────╮\x1b[0m");
    println!("  \x1b[36m│\x1b[0m \x1b[1mJarvis CLI\x1b[0m — Rust TUI                          \x1b[36m│\x1b[0m");
    println!("  \x1b[36m│\x1b[0m \x1b[2mintrospect • synthesize • build\x1b[0m                  \x1b[36m│\x1b[0m");
    println!("  \x1b[36m╰──────────────────────────────────────────────────╯\x1b[0m");
    println!("  \x1b[2mBackend: {url}\x1b[0m");
    if let Some(ref sid) = session_id {
        println!("  \x1b[2mResuming session: {sid}\x1b[0m");
    }
    println!("  \x1b[2mType /help for commands. Ctrl-C twice to exit.\x1b[0m\n");

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

            "/help" => {
                print_help();
                continue;
            }

            _ => {}
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

        // Add to history (skip slash-commands, already handled above)
        history.push(prompt.clone());
        save_history(&history);

        match sse::stream(&url, &prompt, session_id.as_deref(), api_key.as_deref()).await {
            Ok(new_session_id) => {
                println!("  \x1b[2msession: {new_session_id}\x1b[0m\n");
                session_id = Some(new_session_id);
            }
            Err(e) => {
                println!("  \x1b[31m✗ {e}\x1b[0m\n");
            }
        }
    }

    println!("\n  \x1b[2mGoodbye.\x1b[0m\n");
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
    print!("\x1b[2K\r  \x1b[32m❯\x1b[0m ");
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

fn read_input_raw(history: &[String]) -> Option<String> {
    let mut buf = String::new();
    let mut ctrl_c_count = 0u8;
    let mut paste_content: Option<String> = None;
    let mut paste_lines_printed: usize = 0;
    let mut hist_idx: usize = history.len();
    let mut saved_buf = String::new();

    loop {
        if !event::poll(Duration::from_millis(500)).unwrap_or(false) {
            continue;
        }

        match event::read() {
            Ok(Event::Paste(text)) => {
                let text = text.replace("\r\n", "\n").replace('\r', "\n");
                // Single-line paste: just insert into buffer
                if !text.contains('\n') {
                    buf.push_str(&text);
                    print!("\x1b[2K\r  \x1b[32m❯\x1b[0m {buf}");
                    io::stdout().flush().ok();
                } else {
                    paste_lines_printed = show_paste_preview(&text, &buf);
                    paste_content = Some(text);
                }
            }
            Ok(Event::Key(KeyEvent { code, modifiers, .. })) => {
                match (code, modifiers) {
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
                        print!("\x1b[2K\r\n  \x1b[2m(Ctrl-C again to exit)\x1b[0m\r\n  \x1b[32m❯\x1b[0m ");
                        io::stdout().flush().ok();
                        buf.clear();
                    }
                    (KeyCode::Up, _) => {
                        if paste_content.is_none() && !history.is_empty() && hist_idx > 0 {
                            if hist_idx == history.len() {
                                saved_buf = buf.clone();
                            }
                            hist_idx -= 1;
                            buf = history[hist_idx].clone();
                            print!("\x1b[2K\r  \x1b[32m❯\x1b[0m {buf}");
                            io::stdout().flush().ok();
                        }
                    }
                    (KeyCode::Down, _) => {
                        if paste_content.is_none() && hist_idx < history.len() {
                            hist_idx += 1;
                            buf = if hist_idx == history.len() {
                                saved_buf.clone()
                            } else {
                                history[hist_idx].clone()
                            };
                            print!("\x1b[2K\r  \x1b[32m❯\x1b[0m {buf}");
                            io::stdout().flush().ok();
                        }
                    }
                    (KeyCode::Esc, _) => {
                        if paste_content.is_some() {
                            clear_paste_preview(paste_lines_printed);
                            paste_content = None;
                            paste_lines_printed = 0;
                            print!("\x1b[2K\r  \x1b[32m❯\x1b[0m {buf}");
                            io::stdout().flush().ok();
                        }
                    }
                    (KeyCode::Enter, _) => {
                        if let Some(text) = paste_content {
                            if buf.is_empty() {
                                return Some(text);
                            } else {
                                buf.push('\n');
                                buf.push_str(&text);
                                return Some(buf);
                            }
                        }
                        if !buf.is_empty() {
                            return Some(buf);
                        }
                    }
                    (KeyCode::Backspace, _) => {
                        if paste_content.is_none() {
                            if buf.pop().is_some() {
                                print!("\x08 \x08");
                                io::stdout().flush().ok();
                            }
                        }
                        ctrl_c_count = 0;
                    }
                    (KeyCode::Char(c), _) => {
                        if paste_content.is_none() {
                            buf.push(c);
                            print!("{c}");
                            io::stdout().flush().ok();
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
