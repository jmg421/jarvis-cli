mod daemon;
mod queue;
mod render;
mod sse;
mod tui;

use clap::Parser;
use crossterm;

#[derive(Parser)]
#[command(name = "jarvis", about = "Agentic development CLI — introspect • synthesize • build")]
struct Cli {
    /// Prompt to send non-interactively (like `--pipe` but as an arg).
    /// Example: jarvis --prompt "list files in ~/repos"
    #[arg(long, short = 'p')]
    prompt: Option<String>,

    /// Continue an existing session by ID
    #[arg(long, short = 'c')]
    r#continue: Option<String>,

    /// List recent sessions and exit
    #[arg(long, short = 's')]
    sessions: bool,

    /// Enqueue a task for daemon processing and exit
    #[arg(long, short = 'e')]
    enqueue: Option<String>,

    /// Show daemon status and exit
    #[arg(long)]
    status: bool,

    /// Backend URL
    #[arg(long, env = "JARVIS_AGENT_URL", default_value = "http://localhost:8100")]
    url: String,

    /// Do not auto-start the agent daemon (use if running it manually)
    #[arg(long)]
    no_daemon: bool,
}

#[tokio::main]
async fn main() {
    let cli = Cli::parse();

    // --enqueue: add a task to the local queue and exit
    if let Some(task) = cli.enqueue {
        queue::enqueue(&task);
        return;
    }

    // --status: show daemon + queue status and exit
    if cli.status {
        queue::status();
        return;
    }

    if cli.sessions {
        // Ensure agent is reachable first (auto-start unless suppressed)
        if !cli.no_daemon {
            if let Err(e) = daemon::ensure_running(&cli.url).await {
                eprintln!("  \x1b[33m⚠ {e}\x1b[0m");
            }
        }
        match sse::list_sessions(&cli.url).await {
            Ok(sessions) if sessions.is_empty() => {
                println!("  \x1b[2mNo sessions found.\x1b[0m");
            }
            Ok(sessions) => {
                println!("\n  \x1b[1;32mRecent sessions:\x1b[0m");
                for s in sessions {
                    println!("  {s}");
                }
                println!();
            }
            Err(e) => eprintln!("  \x1b[31m✗ {e}\x1b[0m"),
        }
        return;
    }

    // --prompt / stdin pipe mode: read prompt, stream once, print, exit.
    // Usage:
    //   jarvis --prompt "task"
    //   echo "task" | jarvis
    //   cat spec.md | jarvis
    let pipe_prompt = cli.prompt.or_else(|| {
        // Only read stdin when it's not a TTY (i.e. data is being piped in)
        if !is_stdin_tty() {
            let mut buf = String::new();
            use std::io::Read;
            std::io::stdin().read_to_string(&mut buf).ok();
            let trimmed = buf.trim().to_string();
            if !trimmed.is_empty() { Some(trimmed) } else { None }
        } else {
            None
        }
    });

    if let Some(prompt) = pipe_prompt {
        // Ensure daemon is up
        if !cli.no_daemon {
            if let Err(e) = daemon::ensure_running(&cli.url).await {
                eprintln!("  \x1b[33m⚠ {e}\x1b[0m");
            }
        }
        let api_key = tui::load_api_key_pub();
        let (_cancel_tx, cancel_rx) = tokio::sync::watch::channel(false);
        match sse::stream(&cli.url, &prompt, cli.r#continue.as_deref(), api_key.as_deref(), None, cancel_rx).await {
            Ok((session_id, usage, _assistant_text)) => {
                if !usage.is_empty() {
                    let cost = usage.estimated_cost_usd();
                    let iters = if usage.iterations > 0 {
                        format!("  {}↺", usage.iterations)
                    } else {
                        String::new()
                    };
                    eprintln!(
                        "  \x1b[2msession: {session_id}  ·  {}↑ {}↓  ~${cost:.4}{iters}\x1b[0m",
                        tui::fmt_tokens_pub(usage.input_tokens),
                        tui::fmt_tokens_pub(usage.output_tokens),
                    );
                } else {
                    eprintln!("  \x1b[2msession: {session_id}\x1b[0m");
                }
            }
            Err(e) => {
                eprintln!("  \x1b[31m✗ {e}\x1b[0m");
                std::process::exit(1);
            }
        }
        return;
    }

    // Install a panic hook that restores the terminal before printing the
    // panic message.  Without this, a Rust panic while raw mode is active
    // leaves the terminal in raw mode — the shell becomes unusable.
    let default_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        let _ = crossterm::terminal::disable_raw_mode();
        let _ = crossterm::execute!(
            std::io::stdout(),
            crossterm::event::DisableBracketedPaste
        );
        default_hook(info);
    }));

    tui::run(cli.url, cli.r#continue, cli.no_daemon).await;
    // Note: we intentionally do NOT stop the daemon here — it's a long-running
    // service shared across sessions and other clients.
}

/// Returns true if stdin is connected to a terminal (not a pipe/redirect).
fn is_stdin_tty() -> bool {
    #[cfg(unix)]
    {
        extern "C" { fn isatty(fd: i32) -> i32; }
        unsafe { isatty(0) != 0 }
    }
    #[cfg(not(unix))]
    {
        true
    }
}
