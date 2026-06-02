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

    // Kill stale process: check pid file first, then check port
    if let Ok(pid_str) = fs::read_to_string(&pid_path) {
        if let Ok(pid) = pid_str.trim().parse::<u32>() {
            Command::new("kill").arg(pid.to_string()).status().ok();
            std::thread::sleep(Duration::from_millis(300));
            Command::new("kill").args(["-9", &pid.to_string()]).status().ok();
            fs::remove_file(&pid_path).ok();
        }
    }

    // Kill anything else holding the port (stale process without pid file)
    if let Ok(output) = Command::new("lsof")
        .args(["-ti", &format!(":{port}")])
        .output()
    {
        let pids = String::from_utf8_lossy(&output.stdout);
        for pid in pids.split_whitespace() {
            Command::new("kill").args(["-9", pid]).status().ok();
        }
        if !pids.is_empty() {
            std::thread::sleep(Duration::from_millis(500));
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
/// Not called automatically on exit — the agent is a long-running shared service.
#[allow(dead_code)]
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
