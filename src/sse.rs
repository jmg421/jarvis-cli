use futures_util::StreamExt;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tokio::time::timeout;

use crate::render;

/// Token usage returned from a completed stream.
#[derive(Default, Clone, Debug)]
pub struct Usage {
    pub input_tokens: u64,
    pub output_tokens: u64,
    pub cache_read_tokens: u64,
    pub cache_write_tokens: u64,
    pub iterations: u64,
}

impl Usage {
    pub fn is_empty(&self) -> bool {
        self.input_tokens == 0 && self.output_tokens == 0
    }

    /// Estimate cost in USD using Claude Sonnet 3.7 rates
    /// (input: $3/M, output: $15/M, cache read: $0.30/M, cache write: $3.75/M)
    pub fn estimated_cost_usd(&self) -> f64 {
        (self.input_tokens as f64 * 3.0
            + self.output_tokens as f64 * 15.0
            + self.cache_read_tokens as f64 * 0.30
            + self.cache_write_tokens as f64 * 3.75)
            / 1_000_000.0
    }
}

#[derive(Serialize)]
struct RunRequest<'a> {
    prompt: &'a str,
    #[serde(skip_serializing_if = "Option::is_none")]
    session_id: Option<&'a str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    api_key: Option<&'a str>,
    /// Extended-thinking token budget (None = use backend default / no extended thinking)
    #[serde(skip_serializing_if = "Option::is_none")]
    budget_tokens: Option<u32>,
    /// Client working directory for relative path resolution
    #[serde(skip_serializing_if = "Option::is_none")]
    cwd: Option<String>,
}

#[derive(Deserialize)]
struct SseEvent {
    #[serde(rename = "type")]
    event_type: String,
    // text_delta / error / thinking
    #[serde(default)]
    text: Option<String>,
    // thinking
    #[serde(default)]
    thinking: Option<String>,
    // tool_call / tool_result
    #[serde(default)]
    name: Option<String>,
    #[serde(default)]
    input: Option<serde_json::Value>,
    #[serde(default)]
    result: Option<String>,
    // done
    #[serde(default)]
    session_id: Option<String>,
    #[serde(default)]
    usage: Option<serde_json::Value>,
    // context_management
    #[serde(default)]
    chars_removed: Option<u64>,
    // done
    #[serde(default)]
    iterations: Option<u64>,
    // iteration progress
    #[serde(default)]
    current: Option<u64>,
    #[serde(default)]
    max: Option<u64>,
}

/// Sentinel error string returned when the caller cancels via the watch channel.
pub const CANCELLED: &str = "__cancelled__";

/// Stream a prompt to the backend, printing events as they arrive.
/// Returns (session_id, usage, assistant_text) from the done event.
///
/// `cancel` — a `watch::Receiver<bool>`.  When the sender sets the value to
/// `true` the stream loop exits immediately with `Err(CANCELLED)`.
pub async fn stream(
    url: &str,
    prompt: &str,
    session_id: Option<&str>,
    api_key: Option<&str>,
    budget_tokens: Option<u32>,
    mut cancel: tokio::sync::watch::Receiver<bool>,
) -> Result<(String, Usage, String), String> {
    let client = Client::new();

    // ── Cancel-aware HTTP connect ────────────────────────────────────────────
    //
    // Root cause fix: previously client.send().await was NOT inside a
    // select!, so if the user pressed Esc during the connect phase (which
    // can take several seconds on a cold backend start) the cancel signal
    // was set but nobody was watching it yet.  The stream loop would only
    // start checking cancel *after* the connection was established.
    let connect_fut = client
        .post(format!("{url}/stream"))
        .json(&RunRequest { prompt, session_id, api_key, budget_tokens, cwd: Some(std::env::current_dir().unwrap_or_default().to_string_lossy().into_owned()) })
        .header("Accept", "text/event-stream")
        .send();

    let resp = tokio::select! {
        biased;
        _ = cancel.changed() => {
            return Err(CANCELLED.to_string());
        }
        result = connect_fut => {
            result.map_err(|e| format!("Connection failed: {e}"))?
        }
    };

    if !resp.status().is_success() {
        return Err(format!("Backend returned {}", resp.status()));
    }

    // Show animated spinner while we wait for the first event.
    // Dropping the handle stops and clears the spinner.
    let mut spinner: Option<render::SpinnerHandle> = Some(render::thinking());

    let mut stream = resp.bytes_stream();
    let mut buffer = String::new();
    let mut final_session_id = session_id.unwrap_or("unknown").to_string();
    let mut final_usage = Usage::default();
    // Accumulate assistant text for transcript
    let mut assistant_text = String::new();

    loop {
        // Check for cancellation before blocking on the next chunk
        if *cancel.borrow() {
            drop(spinner.take());
            render::finish_thinking();
            render::finish();
            return Err(CANCELLED.to_string());
        }

        // Race the next chunk against a cancel signal and a 180s timeout.
        // cancel.changed() resolves the moment the sender writes `true`.
        let chunk = tokio::select! {
            biased;                          // check cancel first, every iteration
            _ = cancel.changed() => {
                drop(spinner.take());
                render::finish_thinking();
                render::finish();
                return Err(CANCELLED.to_string());
            }
            result = timeout(Duration::from_secs(180), stream.next()) => {
                match result {
                    Ok(Some(c)) => c,
                    Ok(None) => break,
                    Err(_) => {
                        drop(spinner.take());
                        render::finish();
                        return Err("Stream timeout: no data for 180s".to_string());
                    }
                }
            }
        };
        let chunk = chunk.map_err(|e| format!("Stream error: {e}"))?;
        buffer.push_str(&String::from_utf8_lossy(&chunk));

        // Process complete SSE messages (delimited by \n\n)
        while let Some(pos) = buffer.find("\n\n") {
            let message = buffer[..pos].to_string();
            buffer = buffer[pos + 2..].to_string();

            for line in message.lines() {
                if let Some(data) = line.strip_prefix("data: ") {
                    if data == "[DONE]" {
                        drop(spinner.take());
                        render::finish_thinking();
                        render::finish();
                        return Ok((final_session_id, final_usage, assistant_text));
                    }
                    if let Ok(event) = serde_json::from_str::<SseEvent>(data) {
                        // Drop spinner on first real event (clears the line)
                        drop(spinner.take());

                        match event.event_type.as_str() {
                            "thinking" => {
                                // Show agent reasoning in real-time (kiro 2.5.0 parity)
                                if let Some(thought) = event.thinking.as_ref().or(event.text.as_ref()) {
                                    render::thinking_delta(thought);
                                }
                            }
                            "text_delta" => {
                                if let Some(text) = &event.text {
                                    assistant_text.push_str(text);
                                    render::text_delta(text);
                                }
                            }
                            "tool_call" => {
                                if let Some(name) = &event.name {
                                    let preview = event
                                        .input
                                        .as_ref()
                                        .and_then(|inp| render::format_tool_input(name, inp));
                                    render::tool_call(name, preview.as_deref());
                                }
                            }
                            "tool_result" => {
                                if let Some(result) = &event.result {
                                    render::tool_result(result);
                                }
                            }
                            "context_management" => {
                                let chars = event.chars_removed.unwrap_or(0);
                                render::context_management(chars);
                            }
                            "iteration" => {
                                if let (Some(cur), Some(max)) = (event.current, event.max) {
                                    render::iteration_progress(cur, max);
                                }
                            }
                            "done" => {
                                drop(spinner.take());
                                render::finish_thinking(); // close any open thinking block
                                if let Some(sid) = &event.session_id {
                                    final_session_id = sid.clone();
                                }
                                if let Some(iters) = event.iterations {
                                    final_usage.iterations = iters;
                                }
                                if let Some(usage_val) = &event.usage {
                                    if let Some(obj) = usage_val.as_object() {
                                        let get_u64 = |k: &str| {
                                            obj.get(k).and_then(|v| v.as_u64()).unwrap_or(0)
                                        };
                                        final_usage.input_tokens = get_u64("input_tokens");
                                        final_usage.output_tokens = get_u64("output_tokens");
                                        final_usage.cache_read_tokens = get_u64("cache_read_input_tokens");
                                        final_usage.cache_write_tokens = get_u64("cache_creation_input_tokens");
                                    }
                                }
                            }
                            "error" => {
                                if let Some(text) = &event.text {
                                    render::text_delta(&format!(
                                        "\n\x1b[31m✗ Agent error: {text}\x1b[0m\n"
                                    ));
                                }
                            }
                            _ => {}
                        }
                    }
                }
            }
        }
    }

    render::finish_thinking();
    render::finish();
    Ok((final_session_id, final_usage, assistant_text))
}

/// List sessions from the backend. Returns formatted lines ready to print.
pub async fn list_sessions(url: &str) -> Result<Vec<String>, String> {
    let client = Client::new();
    let resp = client
        .get(format!("{url}/sessions"))
        .send()
        .await
        .map_err(|e| format!("Connection failed: {e}"))?;

    #[derive(Deserialize)]
    struct Session {
        session_id: String,
        #[serde(default)]
        updated_at: Option<f64>,
        #[serde(default)]
        message_count: Option<u32>,
        #[serde(default)]
        preview: Option<String>,
    }

    #[derive(Deserialize)]
    #[serde(untagged)]
    enum SessionsResp {
        Structured { sessions: Vec<Session> },
        Plain { sessions: Vec<String> },
    }

    let body: SessionsResp = resp.json().await.map_err(|e| format!("Parse error: {e}"))?;

    let lines = match body {
        SessionsResp::Structured { sessions } => sessions
            .into_iter()
            .map(|s| {
                let ts = s
                    .updated_at
                    .map(|t| {
                        // Format as "MM/DD HH:MM"
                        let secs = t as u64;
                        // Simple wall-clock offset from Unix epoch — good enough for display
                        format_unix_ts(secs)
                    })
                    .unwrap_or_else(|| "?".to_string());
                let msgs = s.message_count.map(|n| format!("{n} msgs")).unwrap_or_default();
                let preview = s.preview.unwrap_or_default();
                let preview = if preview.len() > 60 { format!("{}…", &preview[..57]) } else { preview };
                format!(
                    "\x1b[36m{}\x1b[0m  \x1b[2m{ts}  {msgs}  {preview}\x1b[0m",
                    s.session_id
                )
            })
            .collect(),
        SessionsResp::Plain { sessions } => sessions,
    };

    Ok(lines)
}

/// Delete a session from the backend.
pub async fn delete_session(url: &str, session_id: &str) -> Result<(), String> {
    let client = Client::new();
    let resp = client
        .delete(format!("{url}/sessions/{session_id}"))
        .send()
        .await
        .map_err(|e| format!("Connection failed: {e}"))?;

    if resp.status().is_success() {
        Ok(())
    } else {
        Err(format!("Backend returned {}", resp.status()))
    }
}

/// Minimal Unix timestamp → "MM/DD HH:MM" formatter (no external time crate).
fn format_unix_ts(secs: u64) -> String {
    // Days since epoch
    let days = secs / 86400;
    let time_of_day = secs % 86400;
    let h = time_of_day / 3600;
    let m = (time_of_day % 3600) / 60;

    // Compute year/month/day using the Gregorian proleptic calendar algorithm
    let z = days as i64 + 719468;
    let era = z.div_euclid(146097);
    let doe = z.rem_euclid(146097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let year = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = if month <= 2 { year + 1 } else { year };
    let _ = year; // suppress unused warning — we only show MM/DD

    format!("{:02}/{:02} {:02}:{:02}", month, day, h, m)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_format_unix_ts_known_date() {
        // 2024-01-15 14:30:00 UTC = 1705329000
        let s = format_unix_ts(1705329000);
        assert_eq!(s, "01/15 14:30");
    }

    #[test]
    fn test_format_unix_ts_epoch() {
        // 1970-01-01 00:00:00 UTC
        let s = format_unix_ts(0);
        assert_eq!(s, "01/01 00:00");
    }
}
