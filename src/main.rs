mod daemon;
mod render;
mod sse;
mod tui;

use clap::Parser;

#[derive(Parser)]
#[command(name = "jarvis-cli", about = "Agentic development CLI")]
struct Cli {
    /// Continue an existing session
    #[arg(long)]
    r#continue: Option<String>,

    /// List sessions
    #[arg(long)]
    sessions: bool,

    /// Backend URL
    #[arg(long, env = "JARVIS_AGENT_URL", default_value = "http://localhost:8100")]
    url: String,
}

#[tokio::main]
async fn main() {
    let cli = Cli::parse();

    if cli.sessions {
        match sse::list_sessions(&cli.url).await {
            Ok(sessions) => {
                for s in sessions {
                    println!("  {s}");
                }
            }
            Err(e) => eprintln!("  Error: {e}"),
        }
        return;
    }

    tui::run(cli.url, cli.r#continue).await;
    daemon::stop();
}
