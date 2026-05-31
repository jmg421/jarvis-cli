use std::io::{self, Write};

static mut IN_TEXT: bool = false;

pub fn text_delta(text: &str) {
    unsafe {
        if !IN_TEXT {
            print!("\n  ");
            IN_TEXT = true;
        }
    }
    // Handle newlines with indentation
    let formatted = text.replace('\n', "\n  ");
    print!("{formatted}");
    io::stdout().flush().ok();
}

pub fn tool_call(name: &str) {
    unsafe {
        if IN_TEXT {
            println!();
            IN_TEXT = false;
        }
    }
    println!("\n  \x1b[33m⚡ {name}\x1b[0m");
}

pub fn tool_result(result: &str) {
    let preview = if result.len() > 120 {
        format!("{}…", &result[..120])
    } else {
        result.to_string()
    };
    println!("  \x1b[2m→ {preview}\x1b[0m");
}

pub fn finish() {
    unsafe {
        if IN_TEXT {
            IN_TEXT = false;
        }
    }
    println!("\n");
}
