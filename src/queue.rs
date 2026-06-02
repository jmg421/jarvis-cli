/// Local task queue — mirrors jarvis-cli's Python queue.json format.
/// Used by `--enqueue` / `--status` subcommands.
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;

fn queue_dir() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".jarvis_cli")
}

fn queue_file() -> PathBuf {
    queue_dir().join("queue.json")
}

fn completed_file() -> PathBuf {
    queue_dir().join("completed.json")
}

fn pid_file() -> PathBuf {
    queue_dir().join("daemon.pid")
}

#[derive(Serialize, Deserialize, Clone)]
pub struct Task {
    pub id: String,
    pub task: String,
    pub status: String,
    pub created_at: String,
}

fn load_tasks(path: &PathBuf) -> Vec<Task> {
    fs::read_to_string(path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

fn save_tasks(path: &PathBuf, tasks: &[Task]) {
    fs::create_dir_all(queue_dir()).ok();
    if let Ok(json) = serde_json::to_string_pretty(tasks) {
        fs::write(path, json).ok();
    }
}

fn daemon_running() -> Option<u32> {
    let pid_str = fs::read_to_string(pid_file()).ok()?;
    let pid: u32 = pid_str.trim().parse().ok()?;
    // send signal 0 to test if process is alive (Unix only)
    #[cfg(unix)]
    {
        let alive = std::process::Command::new("kill")
            .args(["-0", &pid.to_string()])
            .status()
            .map(|s| s.success())
            .unwrap_or(false);
        if alive { Some(pid) } else { None }
    }
    #[cfg(not(unix))]
    Some(pid)
}

/// Add a task to the queue.
pub fn enqueue(task: &str) {
    let mut queue = load_tasks(&queue_file());
    // Use a simple unique ID based on time
    let id = format!("t{}", std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0));
    let now = chrono_now();
    let entry = Task {
        id,
        task: task.to_string(),
        status: "queued".to_string(),
        created_at: now,
    };
    queue.push(entry);
    save_tasks(&queue_file(), &queue);
    println!("  \x1b[32m✓ Task queued:\x1b[0m {task}");
}

/// Show daemon + queue status.
pub fn status() {
    let queue = load_tasks(&queue_file());
    let completed = load_tasks(&completed_file());

    let queued: Vec<_> = queue.iter().filter(|t| t.status == "queued").collect();
    let processing: Vec<_> = queue.iter().filter(|t| t.status == "processing").collect();

    println!("\n  \x1b[1;36mJarvis Daemon Status\x1b[0m");
    println!("  \x1b[2m─────────────────────────────────────\x1b[0m");

    match daemon_running() {
        Some(pid) => println!("  \x1b[32m🟢 Running\x1b[0m  \x1b[2mPID: {pid}\x1b[0m"),
        None => println!("  \x1b[31m🔴 Stopped\x1b[0m"),
    }

    println!("  \x1b[2m─────────────────────────────────────\x1b[0m");
    println!("  \x1b[33mQueue:\x1b[0m");
    println!("    📝 Queued: {}", queued.len());
    println!("    ⚡ Processing: {}", processing.len());

    for t in &queued {
        let preview = if t.task.len() > 60 { format!("{}…", &t.task[..57]) } else { t.task.clone() };
        println!("    \x1b[2m• {preview}\x1b[0m");
    }
    for t in &processing {
        let preview = if t.task.len() > 60 { format!("{}…", &t.task[..57]) } else { t.task.clone() };
        println!("    \x1b[33m⚡ {preview}\x1b[0m");
    }

    println!("  \x1b[2m─────────────────────────────────────\x1b[0m");
    println!("  \x1b[32mCompleted:\x1b[0m {}", completed.len());
    println!();
}

fn chrono_now() -> String {
    // ISO8601 without external deps
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let (y, mo, d, h, min, s) = unix_to_ymdhms(secs);
    format!("{y:04}-{mo:02}-{d:02}T{h:02}:{min:02}:{s:02}Z")
}

fn unix_to_ymdhms(secs: u64) -> (i32, u32, u32, u32, u32, u32) {
    let s = secs % 60;
    let min = (secs / 60) % 60;
    let h = (secs / 3600) % 24;
    let days = secs / 86400;
    let z = days as i64 + 719468;
    let era = z.div_euclid(146097);
    let doe = z.rem_euclid(146097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = if month <= 2 { y + 1 } else { y };
    (year as i32, month as u32, day as u32, h as u32, min as u32, s as u32)
}
