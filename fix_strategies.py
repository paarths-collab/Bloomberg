#!/usr/bin/env python3
"""
Script to fix missing finalize_trades parameter in all strategy files.
"""

import os
import re

def fix_strategy_file(filepath):
    """Fix a single strategy file by adding finalize_trades parameter."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Pattern to find Strategy class definitions and add finalize_trades
        pattern = r'(class\s+\w+\(Strategy\):\s*\n(?:\s+\w+\s*=\s*[^\n]+\n)*)'
        
        def add_finalize_trades(match):
            class_def = match.group(1)
            # Check if finalize_trades already exists
            if 'finalize_trades' in class_def:
                return class_def
            
            # Add finalize_trades parameter
            lines = class_def.strip().split('\n')
            lines.append('        finalize_trades = True')
            return '\n'.join(lines) + '\n'
        
        # Apply the fix
        fixed_content = re.sub(pattern, add_finalize_trades, content)
        
        # Only write if content changed
        if fixed_content != content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(fixed_content)
            print(f"Fixed: {os.path.basename(filepath)}")
            return True
        else:
            print(f"No changes needed: {os.path.basename(filepath)}")
            return False
            
    except Exception as e:
        print(f"Error processing {filepath}: {e}")
        return False

def main():
    """Main function to fix all strategy files."""
    strategies_dir = "strategies"
    fixed_count = 0
    
    for filename in os.listdir(strategies_dir):
        if filename.endswith('.py') and filename != '__init__.py':
            filepath = os.path.join(strategies_dir, filename)
            if fix_strategy_file(filepath):
                fixed_count += 1
    
    print(f"\nFixed {fixed_count} strategy files.")

if __name__ == "__main__":
    main()
