#!/usr/bin/env python3
"""
Test the paste fix by simulating the jarvis-cli input behavior
"""

import sys
import readline

CYAN = "\033[1;36m"
GREEN = "\033[1;32m" 
YELLOW = "\033[1;33m"
DIM = "\033[2m"
RESET = "\033[0m"

def _enable_bracketed_paste():
    """Enable bracketed paste mode for better paste handling."""
    try:
        # Enable bracketed paste mode (if terminal supports it)
        sys.stdout.write("\033[?2004h")
        sys.stdout.flush()
        print(f"  {DIM}(enabled bracketed paste){RESET}")
    except:
        pass

def _disable_bracketed_paste():
    """Disable bracketed paste mode."""
    try:
        sys.stdout.write("\033[?2004l") 
        sys.stdout.flush()
        print(f"  {DIM}(disabled bracketed paste){RESET}")
    except:
        pass

def test_paste_input():
    """Test the improved paste input handling"""
    
    _enable_bracketed_paste()
    
    try:
        print(f"""
{CYAN}╭{'─' * 50}╮{RESET}
{CYAN}│{RESET} Test: Jarvis CLI Paste Fix                     {CYAN}│{RESET}
{CYAN}╰{'─' * 50}╯{RESET}

Test the paste behavior:
1. Type: "check file "
2. Then paste a filename
3. The result should preserve both parts

{DIM}(Press Ctrl+C to exit){RESET}
""")
        
        while True:
            try:
                first_line = input(f"  {GREEN}❯{RESET} ")
                
                # Clean up bracketed paste markers if present
                if first_line.startswith('\033[200~') and first_line.endswith('\033[201~'):
                    # Remove bracketed paste markers
                    original = first_line
                    first_line = first_line[6:-6]
                    print(f"  {DIM}(cleaned paste markers: {len(original)} -> {len(first_line)} chars){RESET}")
                
                # Debug: show what we actually received
                print(f"  {CYAN}Raw input:{RESET} {repr(first_line)}")
                print(f"  {CYAN}Length:{RESET} {len(first_line)} chars")
                
                if len(first_line) > 100:
                    print(f"  {DIM}(received long input: {len(first_line)} chars){RESET}")
                
                # Check if the input contains newlines
                if '\n' in first_line:
                    lines = first_line.splitlines()
                    print(f"  {CYAN}Multiline detected:{RESET} {len(lines)} lines")
                    for i, line in enumerate(lines[:3]):  # Show first 3 lines
                        print(f"    {i+1}: {repr(line)}")
                    if len(lines) > 3:
                        print(f"    ... and {len(lines)-3} more lines")
                else:
                    print(f"  {CYAN}Single line:{RESET} {repr(first_line.strip())}")
                
                print()
                
            except KeyboardInterrupt:
                print(f"\n  {YELLOW}Exiting...{RESET}")
                break
            except EOFError:
                break
                
    finally:
        _disable_bracketed_paste()

if __name__ == "__main__":
    test_paste_input()