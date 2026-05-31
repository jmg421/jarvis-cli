use futures_util::StreamExt;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tokio::time::timeout;

use crate::render;

#[derive(Serialize)]
struct RunRequest<'a> {
    prompt: &'a str,
    #[serde(skip_serializing_if = "Option::is_none")]
    session_id: Option<&'a str>,
    #[serde(skip_serializing_if = "Option::is_none")]
    api_key: Option<&'a str>,
}

#[derive(Deserialize)]
struct SseEvent {
    #[serde(rename = "type")]
    event_type: String,
    #[serde(default)]
    text: Option<String>,
    #[serde(default)]
    name: Option<String>,
    #[serde(default)]
    result: Option<String>,
    #[serde(default)]
    session_id: Option<String>,
}

/// Stream a prompt to the backend, printing events as they arrive.
/// Returns the session_id from the done event.
pub async fn stream(url: &str, prompt: &str, session_id: Option<&str>, api_key: Option<&str>) -> Result<String, String> {
    let client = Client::new();
    let resp = client
        .post(format!("{url}/stream"))
        .json(&RunRequest { prompt, session_id, api_key })
        .header("Accept", "text/event-stream")
        .send()
        .await
        .map_err(|e| format!("Connection failed: {e}"))?;

    if !resp.status().is_success() {
        return Err(format!("Backend returned {}", resp.status()));
    }

    let mut stream = resp.bytes_stream();
    let mut buffer = String::new();
    let mut final_session_id = session_id.unwrap_or("unknown").to_string();

    while let Some(chunk) = match timeout(Duration::from_secs(120), stream.next()).await {
        Ok(Some(chunk)) => Some(chunk),
        Ok(None) => None,
        Err(_) => {
            render::finish();
            return Err("Stream timeout: no data for 120s".to_string());
        }
    } {
        let chunk = chunk.map_err(|e| format!("Stream error: {e}"))?;
        buffer.push_str(&String::from_utf8_lossy(&chunk));

        // Process complete SSE lines
        while let Some(pos) = buffer.find("\n\n") {
            let message = buffer[..pos].to_string();
            buffer = buffer[pos + 2..].to_string();

            for line in message.lines() {
                if let Some(data) = line.strip_prefix("data: ") {
                    if data == "[DONE]" {
                        render::finish();
                        return Ok(final_session_id);
                    }
                    if let Ok(event) = serde_json::from_str::<SseEvent>(data) {
                        match event.event_type.as_str() {
                            "text_delta" => {
                                if let Some(text) = &event.text {
                                    render::text_delta(text);
                                }
                            }
                            "tool_call" => {
                                if let Some(name) = &event.name {
                                    render::tool_call(name);
                                }
                            }
                            "tool_result" => {
                                if let Some(result) = &event.result {
                                    render::tool_result(result);
                                }
                            }
                            "done" => {
                                if let Some(sid) = &event.session_id {
                                    final_session_id = sid.clone();
                                }
                            }
                            _ => {}
                        }
                    }
                }
            }
        }
    }

    render::finish();
    Ok(final_session_id)
}

/// List sessions from the backend.
pub async fn list_sessions(url: &str) -> Result<Vec<String>, String> {
    let client = Client::new();
    let resp = client
        .get(format!("{url}/sessions"))
        .send()
        .await
        .map_err(|e| format!("Connection failed: {e}"))?;

    #[derive(Deserialize)]
    struct SessionsResp {
        sessions: Vec<String>,
    }

    let body: SessionsResp = resp.json().await.map_err(|e| format!("Parse error: {e}"))?;
    Ok(body.sessions)
}
