import os
import re

def clean_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Comment out decorators
    content = re.sub(r'^(@st\..*?)$', r'# \1', content, flags=re.MULTILINE)
    
    # Just to be safe, comment out any remaining line starting with st.
    # But be careful not to hit strings or comments.
    # Better to just target known usages if possible.
    
    # Additional cleanup for any missed st. calls (like st.dataframe)
    content = re.sub(r'^\s*(st\..*?)$', r'# \1', content, flags=re.MULTILINE)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"Cleaned {filepath}")

def main():
    folder = "strategies"
    for filename in os.listdir(folder):
        if filename.endswith(".py"):
            clean_file(os.path.join(folder, filename))

if __name__ == "__main__":
    main()
