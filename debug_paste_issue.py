#!/usr/bin/env python3
"""
Debug script to understand the paste issue.

This simulates the problem described:
1. User types some text
2. User pastes a filename  
3. The typed text should be preserved

Let's see what input() actually receives in different scenarios.
"""

import readline
import sys

def debug_input_behavior():
    """Test input with different scenarios"""
    
    scenarios = [
        "Test 1: Type some text and press Enter (no paste)",
        "Test 2: Paste multiline content", 
        "Test 3: Type 'check file ' then paste a filename (this is the problem case)"
    ]
    
    for i, scenario in enumerate(scenarios, 1):
        print(f"\n{scenario}")
        print("=" * len(scenario))
        
        try:
            result = input("jarvis> ")
            print(f"Raw input: {repr(result)}")
            print(f"Length: {len(result)}")
            print(f"Contains newlines: {'\\n' in result}")
            
            if '\n' in result:
                lines = result.splitlines()
                print(f"Split into {len(lines)} lines:")
                for j, line in enumerate(lines):
                    print(f"  {j}: {repr(line)}")
            
            # Show what the current jarvis-cli logic would do
            if '\n' in result:
                print(f"Current logic would return: {repr(result.strip())}")
                print("→ This preserves both typed text and pasted content")
            else:
                print(f"Current logic would return: {repr(result.strip())}")
                print("→ Single line, no issue")
                
        except KeyboardInterrupt:
            print("\nSkipped")
            continue
        except EOFError:
            print("EOF")
            break
            
        print()

if __name__ == "__main__":
    print("Paste Behavior Debug Tool")
    print("=" * 30)
    print()
    print("This will help us understand exactly what input() receives")
    print("when you type text and then paste content.")
    print()
    
    debug_input_behavior()