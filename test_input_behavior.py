#!/usr/bin/env python3
"""
Test script to understand the input() behavior with inline pasting.
"""

import readline

def test_input():
    """Test input behavior when pasting mid-prompt"""
    print("Test: Type some text, then paste a filename")
    print("Expected: Prompt text + pasted content should be preserved")
    print()
    
    try:
        result = input("❯ ")
        print(f"Got: {repr(result)}")
        print(f"Contains newlines: {'\\n' in result}")
        if '\n' in result:
            lines = result.splitlines()
            print(f"Lines: {lines}")
            print(f"First line: {repr(lines[0])}")
    except KeyboardInterrupt:
        print("\nCancelled")

if __name__ == "__main__":
    test_input()