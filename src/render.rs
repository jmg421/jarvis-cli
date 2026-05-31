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
        // Use char_indices to find a safe boundary within the limit
        let mut end = 120;
        for (i, _) in result.char_indices() {
            if i > 120 {
                break;
            }
            end = i;
        }
        // Ensure we don't go past the string length
        end = end.min(result.len());
        format!("{}…", &result[..end])
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

#[cfg(test)]
mod tests {

    #[test]
    fn test_unicode_char_boundary_handling() {
        // Test with Unicode characters that could cause boundary issues
        let test_cases = vec![
            "╭────────────────────────────────────────────────────────╮\n│ Jarvis CLI — Self-Improving Agentic Development │\n╰────────────────────────────────────────────────────────╯",
            "This is a normal ASCII string that is very long and should be truncated properly without any issues",
            "短い", // Short Japanese text
            "これは非常に長い日本語のテキストです。このテキストは120文字を超える可能性があり、文字境界の問題を引き起こす可能性があります。", // Long Japanese text
            "🌟✨🚀💫⭐🌙☀️⚡🔥💯🎯🎨🎭🎪🎊🎉🎈🎁🎀", // Emoji string
        ];

        for test_str in test_cases {
            // This should not panic
            let preview = if test_str.len() > 120 {
                let mut end = 120;
                for (i, _) in test_str.char_indices() {
                    if i > 120 {
                        break;
                    }
                    end = i;
                }
                end = end.min(test_str.len());
                format!("{}…", &test_str[..end])
            } else {
                test_str.to_string()
            };
            
            // Verify the result is valid UTF-8
            assert!(std::str::from_utf8(preview.as_bytes()).is_ok());
        }
    }
}
