import os
from dotenv import load_dotenv
import streamlit as st
import anthropic
from typing import Tuple
import sys
from io import StringIO
import contextlib
import traceback
import ast
import re
import time

# Load environment variables at startup
load_dotenv()

class CodeExecutionError(Exception):
    pass

def clean_code_from_response(code_text: str) -> str:
    """Clean the code text from markdown and other formatting"""
    # Remove markdown code blocks
    code_text = re.sub(r'```python\s*\n', '', code_text)
    code_text = re.sub(r'```\s*\n?', '', code_text)
    
    # Remove any leading/trailing whitespace
    code_text = code_text.strip()
    
    # Remove italics and bold formatting
    code_text = re.sub(r'\*\*(.+?)\*\*', r'\1', code_text)  # Bold
    code_text = re.sub(r'\*(.+?)\*', r'\1', code_text)      # Italic
    
    # Remove any commented out markers
    code_text = re.sub(r'^#\s*```.*$', '', code_text, flags=re.MULTILINE)
    
    # Fix any repeated newlines
    code_text = re.sub(r'\n\s*\n\s*\n', '\n\n', code_text)
    
    return code_text

def is_safe_code(code: str) -> bool:
    """Basic security check for code."""
    forbidden = [
        'open(', 'exec(', 'eval(', 'subprocess', 
        'import os', 'import sys', '__import__', 
        'importlib', 'system(', 'popen('
    ]
    return not any(dangerous in code.lower() for dangerous in forbidden)

@contextlib.contextmanager
def capture_output():
    """Capture stdout and stderr"""
    new_out, new_err = StringIO(), StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout, sys.stderr = new_out, new_err
        yield sys.stdout, sys.stderr
    finally:
        sys.stdout, sys.stderr = old_out, old_err

def execute_code(code: str) -> Tuple[str, str, str]:
    """Execute the code and return stdout, stderr, and any exception message."""
    if not is_safe_code(code):
        raise CodeExecutionError("Code contains potentially unsafe operations")

    output, error, exception_msg = "", "", ""
    
    try:
        # Try to import colorama, but have a fallback if it's not installed
        colorama = __import__('colorama')
        colorama.init()
    except ImportError:
        colorama = None
        
    allowed_modules = {
        "random": __import__("random"),
        "math": __import__("math"),
        "datetime": __import__("datetime"),
        "json": __import__("json"),
        "re": __import__("re"),
        "collections": __import__("collections"),
        "itertools": __import__("itertools"),
        "statistics": __import__("statistics"),
        "time": __import__("time")
    }
    
    if colorama:
        allowed_modules.update({
            "colorama": colorama,
            "Fore": colorama.Fore,
            "Back": colorama.Back,
            "Style": colorama.Style
        })
    
    # Add the modules to the globals dict along with builtins
    globals_dict = {
        "__builtins__": __builtins__,
        **allowed_modules
    }
    
    with capture_output() as (out, err):
        try:
            compiled_code = compile(code, '<string>', 'exec')
            local_dict = {}
            exec(compiled_code, globals_dict, local_dict)
            output = out.getvalue()
            error = err.getvalue()
        except Exception as e:
            error = err.getvalue()
            exception_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
    
    return output, error, exception_msg

def parse_claude_response(response: str) -> Tuple[str, str]:
    """Parse Claude's response into feedback and code sections."""
    try:
        feedback = ""
        code = ""
        
        if "---FEEDBACK---" in response:
            feedback = response.split("---FEEDBACK---")[1].split("---CODE---")[0].strip()
            
        if "---CODE---" in response:
            code = response.split("---CODE---")[1].strip()
            code = clean_code_from_response(code)
            
        return feedback, code
    except Exception as e:
        st.error(f"Error parsing response: {e}")
        return response, ""

def process_code(api_key: str, task_description: str, code: str) -> Tuple[str, str]:
    """Process the code using Claude API and return feedback and refined code."""
    client = anthropic.Client(api_key=api_key)
    
    prompt = f"""
Task Description: {task_description}

Original Code:
```python
{code}
```

Please provide:
1. A detailed code review and feedback
2. A refined version of the code that implements the requested changes
3. Make sure the code doesn't require user input and uses test cases instead
4. Prefer using emoji-based output over terminal colors for better compatibility
5. If using colors, use only standard print statements or emojis

Format your response exactly as follows:
---FEEDBACK---
[Your feedback here]
---CODE---
[The refined code here without any markdown formatting or additional explanation within the code section]
"""

    try:
        message = client.messages.create(
            model="claude-3-sonnet-20240229",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}]
        )
        return parse_claude_response(message.content[0].text)
    except Exception as e:
        st.error(f"Error calling Claude API: {e}")
        return "", ""

def main():
    st.set_page_config(
        page_title="AI Code Assistant",
        page_icon="🤖",
        layout="wide"
    )
    
    st.title("🤖 AI Code Assistant")
    
    # Initialize session state
    if 'api_key' not in st.session_state:
        # Try to get API key from environment variables first
        st.session_state.api_key = os.getenv('CLAUDE_API_KEY', '')
    if 'run_clicked' not in st.session_state:
        st.session_state.run_clicked = False
    
    # Settings section with API key in sidebar
    with st.sidebar:
        st.header("Settings")
        api_key = st.text_input(
            "Claude API Key",
            type="password",
            value=st.session_state.api_key,
            help="Enter your Claude API key here. It will be stored in the session."
        )
        st.session_state.api_key = api_key
        
        st.markdown("---")
        st.markdown("""
        ### How to use:
        1. Enter your Claude API key (or set it in .env file)
        2. Describe your task
        3. Paste your code
        4. Click 'Analyze Code' for AI feedback
        5. Use 'Run Code' to test either version
        
        Note: For interactive programs, the code will be modified to use test cases 
        instead of requiring user input.
        """)
    
    # Main content area
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("Input")
        task_description = st.text_area(
            "Task Description",
            height=100,
            placeholder="Describe what you want to achieve with your code..."
        )
        
        code = st.text_area(
            "Your Code",
            height=300,
            placeholder="Paste your code here...",
            help="Paste the code you want Claude to analyze and improve"
        )
        
        col1_1, col1_2 = st.columns(2)
        with col1_1:
            if st.button("Analyze Code", type="primary", disabled=not api_key):
                if not task_description:
                    st.error("Please provide a task description")
                elif not code:
                    st.error("Please provide some code to analyze")
                else:
                    with st.spinner("Analyzing your code..."):
                        feedback, refined_code = process_code(api_key, task_description, code)
                        st.session_state.feedback = feedback
                        st.session_state.refined_code = refined_code
                        # Reset run state when new code is analyzed
                        st.session_state.run_clicked = False
        
        with col1_2:
            if st.button("Run Original Code"):
                with st.spinner("Running code..."):
                    try:
                        output, error, exception = execute_code(code)
                        st.session_state.current_output = output
                        st.session_state.current_error = error
                        st.session_state.current_exception = exception
                        st.session_state.run_clicked = True
                    except CodeExecutionError as e:
                        st.error(str(e))
    
    with col2:
        st.subheader("Output")
        
        # Feedback section
        if 'feedback' in st.session_state and st.session_state.feedback:
            with st.expander("📝 Feedback", expanded=True):
                st.markdown(st.session_state.feedback)
        
        # Refined code section with improved copy functionality
        if 'refined_code' in st.session_state and st.session_state.refined_code:
            with st.expander("✨ Refined Code", expanded=True):
                # Create columns for code and buttons
                code_col, button_col = st.columns([4,1])
                
                # Display code in the main column
                with code_col:
                    st.code(st.session_state.refined_code, language='python')
                
                # Put buttons in the side column
                with button_col:
                    # Copy button using st.download_button
                    st.download_button(
                        label="📋 Copy Code",
                        data=st.session_state.refined_code,
                        file_name="refined_code.py",
                        mime="text/plain",
                        help="Copy the refined code to clipboard",
                        key="copy_button"
                    )
                    
                    if st.button("▶️ Run Code"):
                        st.session_state.run_clicked = True
                        with st.spinner("Running code..."):
                            try:
                                output, error, exception = execute_code(st.session_state.refined_code)
                                st.session_state.current_output = output
                                st.session_state.current_error = error
                                st.session_state.current_exception = exception
                            except CodeExecutionError as e:
                                st.error(str(e))
    
    # New section at the bottom of the page for execution output
    if 'run_clicked' in st.session_state and st.session_state.run_clicked:
        st.markdown("---")
        st.subheader("🖥️ Execution Output")
        
        output_container = st.container()
        with output_container:
            if hasattr(st.session_state, 'current_output') and st.session_state.current_output:
                st.markdown("**Program Output:**")
                st.code(st.session_state.current_output, language='python')
            if hasattr(st.session_state, 'current_error') and st.session_state.current_error:
                st.markdown("**Error Output:**")
                st.code(st.session_state.current_error, language='bash')
            if hasattr(st.session_state, 'current_exception') and st.session_state.current_exception:
                st.markdown("**Exception:**")
                st.code(st.session_state.current_exception, language='bash')

if __name__ == "__main__":
    main()
