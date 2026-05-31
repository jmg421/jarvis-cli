use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::time::Duration;

fn pid_file() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".jarvis_cli")
        .join("agent.pid")
}

fn agent_dir() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("repos")
        .join("jarvis-agent")
}

/// Check if the agent backend is reachable.
pub async fn is_running(url: &str) -> bool {
    reqwest::Client::new()
        .get(format!("{url}/health"))
        .timeout(Duration::from_secs(2))
        .send()
        .await
        .is_ok()
}

/// Start the agent backend as a daemon process. Returns Ok if started or already running.
pub async fn ensure_running(url: &str) -> Result<(), String> {
    if is_running(url).await {
        return Ok(());
    }

    let agent_path = agent_dir();
    if !agent_path.join("jarvis_agent").join("server.py").exists() {
        return Err(format!(
            "Agent not found at {}",
            agent_path.display()
        ));
    }

    // Parse port from url
    let port = url
        .rsplit(':')
        .next()
        .and_then(|p| p.trim_end_matches('/').parse::<u16>().ok())
        .unwrap_or(8100);

    let pid_path = pid_file();
    fs::create_dir_all(pid_path.parent().unwrap()).ok();

    // Kill stale process if pid file exists
    if let Ok(pid_str) = fs::read_to_string(&pid_path) {
        if let Ok(pid) = pid_str.trim().parse::<u32>() {
            // Check if process is alive
            let alive = Command::new("kill")
                .args(["-0", &pid.to_string()])
                .status()
                .map(|s| s.success())
                .unwrap_or(false);
            if !alive {
                fs::remove_file(&pid_path).ok();
            }
        }
    }

    eprintln!("  \x1b[2mStarting jarvis-agent daemon on port {port}...\x1b[0m");

    let child = Command::new("uvicorn")
        .args([
            "jarvis_agent.server:app",
            "--host", "127.0.0.1",
            "--port", &port.to_string(),
            "--log-level", "warning",
        ])
        .current_dir(&agent_path)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map_err(|e| format!("Failed to start uvicorn: {e}"))?;

    fs::write(&pid_path, child.id().to_string()).ok();

    // Wait for it to come up
    for _ in 0..30 {
        tokio::time::sleep(Duration::from_millis(200)).await;
        if is_running(url).await {
            eprintln!("  \x1b[2m✓ Agent running (pid {})\x1b[0m", child.id());
            return Ok(());
        }
    }

    Err("Agent started but not responding after 6s".to_string())
}

/// Stop the daemon if we started it.
pub fn stop() {
    let pid_path = pid_file();
    if let Ok(pid_str) = fs::read_to_string(&pid_path) {
        if let Ok(pid) = pid_str.trim().parse::<u32>() {
            Command::new("kill")
                .arg(pid.to_string())
                .status()
                .ok();
            fs::remove_file(&pid_path).ok();
        }
    }
}
