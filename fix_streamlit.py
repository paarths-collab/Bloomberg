import os
import re

def clean_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Comment out imports
    content = re.sub(r'^(import streamlit as st)', r'# \1', content, flags=re.MULTILINE)
    content = re.sub(r'^(from streamlit)', r'# \1', content, flags=re.MULTILINE)

    # Replace st calls with print or pass
    # st.write(x) -> print(x)
    content = re.sub(r'st\.write\((.*?)\)', r'print(\1)', content)
    content = re.sub(r'st\.error\((.*?)\)', r'print("ERROR:", \1)', content)
    content = re.sub(r'st\.warning\((.*?)\)', r'print("WARNING:", \1)', content)
    content = re.sub(r'st\.info\((.*?)\)', r'print("INFO:", \1)', content)
    content = re.sub(r'st\.success\((.*?)\)', r'print("SUCCESS:", \1)', content)
    
    # Remove UI specific calls
    content = re.sub(r'st\.set_page_config.*?\n', '', content)
    content = re.sub(r'st\.title.*?\n', '', content)
    content = re.sub(r'st\.header.*?\n', '', content)
    content = re.sub(r'st\.subheader.*?\n', '', content)
    content = re.sub(r'st\.markdown.*?\n', '', content)
    content = re.sub(r'st\.sidebar.*?\n', '', content)
    
    # Handle with st.spinner
    content = re.sub(r'with st\.spinner.*?:', 'if True:', content)

    # Remove if __name__ == "__main__": and everything after
    if 'if __name__ == "__main__":' in content:
        content = content.split('if __name__ == "__main__":')[0]
        print(f"Truncated main block in {filepath}")

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

def main():
    folder = "strategies"
    for filename in os.listdir(folder):
        if filename.endswith(".py"):
            clean_file(os.path.join(folder, filename))
            
    # Also clean agents if they have it
    agent_folder = "agents"
    for filename in os.listdir(agent_folder):
        if filename.endswith(".py"):
            clean_file(os.path.join(agent_folder, filename))

if __name__ == "__main__":
    main()
