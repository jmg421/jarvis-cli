mod daemon;
mod queue;
mod render;
mod sse;
mod tui;

use clap::Parser;

#[derive(Parser)]
#[command(name = "jarvis", about = "Agentic development CLI — introspect • synthesize • build")]
struct Cli {
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

    tui::run(cli.url, cli.r#continue, cli.no_daemon).await;
    // Note: we intentionally do NOT stop the daemon here — it's a long-running
    // service shared across sessions and other clients. Use `daemon::stop()`
    // explicitly only when you want to tear down the agent.
}
