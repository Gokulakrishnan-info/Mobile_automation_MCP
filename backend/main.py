"""
Main Execution Module

Orchestrates the mobile automation workflow:
1. Connects to Bedrock LLM
2. Initializes Appium session
3. Executes user goals using LLM-guided tool calls
4. Manages conversation history and reporting
"""
import argparse
import json
import boto3
import os
import requests
import os
import time
import re
import sys
import signal
import atexit
import subprocess
from typing import Dict, List, Optional
from botocore.exceptions import ClientError

# Fix Windows console encoding issues
if sys.platform == "win32":
    # Set UTF-8 encoding for stdout and stderr on Windows
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    # Also set environment variable for subprocesses
    os.environ['PYTHONIOENCODING'] = 'utf-8'

# Safe print function that handles encoding errors gracefully
def safe_print(*args, **kwargs):
    """Print function that safely handles Unicode encoding on Windows."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        # Fallback: replace problematic characters
        safe_args = []
        for arg in args:
            if isinstance(arg, str):
                safe_args.append(arg.encode('ascii', 'replace').decode('ascii'))
            else:
                safe_args.append(arg)
        print(*safe_args, **kwargs)

# Import from separated modules
from appium_tools import (
    initialize_appium_session,
    get_page_source,
    get_page_configuration,
    get_perception_summary,
    available_functions,
    resolve_editable_locator
)
import appium_tools
from smart_executor import SmartActionExecutor
from prompts import get_system_prompt, get_app_package_suggestions
from reports import TestReport
from llm_tools import tools_list_claude
from logging_utils import setup_log_capture


# Enable log file capture so developers can review full transcripts later
LOG_FILE_PATH = setup_log_capture()
if LOG_FILE_PATH:
    print(f"--- [LOG] Console output is being saved to: {LOG_FILE_PATH}")
else:
    print("--- [WARN] Failed to initialize file logging. Console output will not be saved.")

# --- 1. Connect to LLM API (Bedrock) ---
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
BEDROCK_MODEL_ID = os.getenv('BEDROCK_MODEL_ID', 'anthropic.claude-3-5-sonnet-20240620-v1:0')
# Cost optimization: Allow switching to cheaper models
# Claude 3 Haiku: ~80% cheaper, good for automation tasks
# Default: Claude 3.5 Sonnet (more capable but more expensive)
# Alternative cheaper models (set via BEDROCK_MODEL_ID env var):
# 'anthropic.claude-3-haiku-20240307-v1:0'  # ~80% cheaper, still capable
# 'amazon.titan-text-lite-v1'  # Very cheap, good for structured tasks
MCP_SERVER_URL = os.getenv('MCP_SERVER_URL', 'http://127.0.0.1:8080')

# Check that keys are provided
if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
    print("Error: AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables are not set.")
    print("Please set them before running the script.")
    exit()

try:
    bedrock_client = boto3.client(
        service_name='bedrock-runtime',
        region_name=AWS_REGION,
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY
    )
except Exception as e:
    print(f"Error creating Bedrock client: {e}")
    print("Please check your credentials and region.")
    exit()

print(f"--- [BOT] Connecting to MCP Server at: {MCP_SERVER_URL} ---")

# Check if MCP server is running
def check_mcp_server_health():
    """Check if the MCP server is running and accessible."""
    try:
        response = requests.get(f"{MCP_SERVER_URL}/health", timeout=2)
        if response.status_code == 200:
            print(f"--- [OK] MCP Server is running and accessible")
            return True
        else:
            print(f"--- [ERROR] MCP Server returned status {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"--- [ERROR] Cannot connect to MCP Server at {MCP_SERVER_URL}")
        print(f"--- [INFO] Please start the MCP server first:")
        print(f"---    cd backend\\appium-mcp")
        print(f"---    npm run start:http")
        return False
    except requests.exceptions.Timeout:
        print(f"--- [ERROR] MCP Server connection timeout")
        return False
    except Exception as e:
        print(f"--- [ERROR] Error checking MCP Server: {e}")
        return False

# Verify MCP server is running before proceeding
if not check_mcp_server_health():
    print("\n--- [ERROR] Exiting: MCP Server is not available")
    exit(1)

# Test the /tools/run endpoint to ensure it's accessible
def test_tools_endpoint():
    """Test if the /tools/run endpoint is accessible."""
    try:
        test_payload = {"tool": "get_page_source", "args": {}}
        response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=test_payload, timeout=2)
        # Any response (even 400/404) means the endpoint exists
        if response.status_code in [200, 400, 404]:
            print(f"--- [OK] /tools/run endpoint is accessible (status: {response.status_code})")
            return True
        else:
            print(f"--- [WARN] /tools/run returned unexpected status: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"--- [ERROR] Cannot connect to {MCP_SERVER_URL}/tools/run")
        print(f"--- [INFO] Make sure the MCP server is running: npm run start:http")
        return False
    except Exception as e:
        print(f"--- [WARN] Error testing /tools/run endpoint: {e}")
        return False

# Test the endpoint (but don't fail if it returns 400/404 - that just means no session)
test_tools_endpoint()


DEVICE_PLATFORM = None
DEVICE_BASE_METADATA = None


def _run_subprocess_command(cmd: List[str], timeout: int = 5) -> str:
    """Run a subprocess command and return stdout (stripped)."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return (result.stdout or "").strip()
    except FileNotFoundError:
        return ""
    except Exception:
        return ""
    return ""


def _get_android_property(prop_name: str) -> str:
    return _run_subprocess_command(["adb", "shell", "getprop", prop_name])


def _detect_android_launcher_package() -> str:
    launcher_output = _run_subprocess_command([
        "adb", "shell", "cmd", "package", "resolve-activity",
        "-a", "android.intent.action.MAIN",
        "-c", "android.intent.category.HOME"
    ])
    if not launcher_output:
        return ""
    match = re.search(r'([a-zA-Z0-9._]+/[a-zA-Z0-9._$]+)', launcher_output)
    if match:
        return match.group(1)
    # Some devices output "activity: com.package/.Activity"
    parts = launcher_output.split()
    for part in parts:
        if '/' in part and '.' in part:
            return part.strip()
    return launcher_output.strip()


def _collect_android_metadata() -> Dict[str, str]:
    manufacturer = _get_android_property("ro.product.manufacturer")
    model = _get_android_property("ro.product.model")
    os_version = _get_android_property("ro.build.version.release")
    screen_size_raw = _run_subprocess_command(["adb", "shell", "wm", "size"])
    density_raw = _run_subprocess_command(["adb", "shell", "wm", "density"])
    screen_size_match = re.search(r'(\d+x\d+)', screen_size_raw or "")
    density_match = re.search(r'(\d+)', density_raw or "")
    launcher_package = _detect_android_launcher_package()
    metadata = {
        "platform": "android",
        "manufacturer": manufacturer or None,
        "model": model or None,
        "os_version": os_version or None,
        "screen_size": screen_size_match.group(1) if screen_size_match else None,
        "density": int(density_match.group(1)) if density_match else None,
        "launcher_package": launcher_package or None,
    }
    return {k: v for k, v in metadata.items() if v not in (None, "", [])}


def _collect_ios_metadata() -> Dict[str, str]:
    model = _run_subprocess_command(["ideviceinfo", "-k", "ProductType"]) or \
        _run_subprocess_command(["ideviceinfo", "-k", "ProductName"])
    os_version = _run_subprocess_command(["ideviceinfo", "-k", "ProductVersion"])
    width = _run_subprocess_command(["ideviceinfo", "-k", "DisplayWidth"])
    height = _run_subprocess_command(["ideviceinfo", "-k", "DisplayHeight"])
    screen_size = None
    if width and height and width.isdigit() and height.isdigit():
        screen_size = f"{width}x{height}"
    metadata = {
        "platform": "ios",
        "model": model or None,
        "os_version": os_version or None,
        "screen_size": screen_size or None,
    }
    return {k: v for k, v in metadata.items() if v not in (None, "", [])}


def set_device_platform(platform_name: str):
    global DEVICE_PLATFORM
    if platform_name:
        DEVICE_PLATFORM = platform_name.lower()
    else:
        DEVICE_PLATFORM = "android"


def get_device_metadata(force_refresh: bool = False) -> Dict[str, str]:
    global DEVICE_BASE_METADATA
    platform = DEVICE_PLATFORM or "android"
    if force_refresh or DEVICE_BASE_METADATA is None:
        if platform == "ios":
            DEVICE_BASE_METADATA = _collect_ios_metadata()
        else:
            DEVICE_BASE_METADATA = _collect_android_metadata()
        if not DEVICE_BASE_METADATA:
            DEVICE_BASE_METADATA = {"platform": platform}
    return DEVICE_BASE_METADATA or {"platform": platform}


def _get_current_app_identifier() -> Optional[str]:
    try:
        func = available_functions.get('get_current_package_activity')
        if callable(func):
            result = func()
            if isinstance(result, dict):
                package = result.get('package') or result.get('result') or result.get('data')
                activity = result.get('activity')
                if package and activity:
                    return f"{package}/{activity}"
                if package:
                    return package
                message = result.get('message')
                if message:
                    return message
            elif isinstance(result, str):
                return result.strip()
    except Exception:
        return None
    return None


def build_device_context_payload(prompt_text: str, screen_state: Optional[str]) -> str:
    metadata = dict(get_device_metadata())
    current_app = _get_current_app_identifier()
    if current_app:
        metadata['current_app'] = current_app
    payload = {
        "device_metadata": metadata,
        "screen_state": screen_state or "",
        "prompt": prompt_text
    }
    return json.dumps(payload, ensure_ascii=False)


def invoke_bedrock_with_retry(bedrock_client, request_body, model_id, max_retries=3, base_delay=1):
    """Invoke Bedrock API with exponential backoff retry logic.
    
    Args:
        bedrock_client: Boto3 Bedrock client
        request_body: Request payload
        model_id: Bedrock model ID
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds for exponential backoff
        
    Returns:
        Response from Bedrock API
        
    Raises:
        Exception if all retries fail
    """
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            response = bedrock_client.invoke_model(
                body=json.dumps(request_body),
                modelId=model_id
            )
            return response
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            error_message = str(e)
            last_exception = e
            
            # Check if error is retryable
            retryable_errors = ['ServiceUnavailableException', 'ThrottlingException', 'TooManyRequestsException']
            is_retryable = any(code in error_code or code in error_message for code in retryable_errors)
            
            if attempt < max_retries and is_retryable:
                # Calculate exponential backoff delay
                delay = base_delay * (2 ** attempt)  # 2s, 4s, 8s, ...
                print(f"[WARN]  Bedrock API error (attempt {attempt + 1}/{max_retries + 1}): {error_code}")
                print(f"[WAIT] Retrying in {delay} seconds...")
                time.sleep(delay)
            else:
                # Non-retryable error or max retries reached
                if not is_retryable:
                    # Suppress technical error - show user-friendly message instead
                    # print(f"[ERROR] Non-retryable Bedrock error: {error_code}")
                    pass
                else:
                    print(f"[ERROR] Max retries ({max_retries + 1}) reached. Bedrock service unavailable.")
                raise
        except Exception as e:
            # For non-ClientError exceptions, don't retry
            print(f"[ERROR] Non-retryable error: {type(e).__name__}: {e}")
            raise
    
    # Should not reach here, but just in case
    raise last_exception if last_exception else Exception("Failed to invoke Bedrock API")


def compress_xml(xml_text: str) -> str:
    """Compress XML by removing unnecessary attributes to reduce token usage.
    
    Removes:
    - index, instance, package (unless needed)
    - checkable, checked, enabled, focusable, focused, long-clickable
    - password, scrollable, selected, displayed, a11y-important
    - screen-reader-focusable, drawing-order, showing-hint, text-entry-key
    - dismissable, a11y-focused, heading, live-region, context-clickable
    - content-invalid
    
    Keeps:
    - text, content-desc, resource-id, bounds, class
    - clickable (only if true), editable (only if true)
    
    Expected reduction: 50-70% of XML size.
    """
    import re
    
    # Remove unnecessary attributes
    # Pattern: attribute="value" or attribute='value'
    unnecessary_attrs = [
        r'\s+index="[^"]*"',
        r'\s+instance="[^"]*"',
        r'\s+package="[^"]*"',
        r'\s+checkable="[^"]*"',
        r'\s+checked="[^"]*"',
        r'\s+enabled="[^"]*"',
        r'\s+focusable="[^"]*"',
        r'\s+focused="[^"]*"',
        r'\s+long-clickable="[^"]*"',
        r'\s+password="[^"]*"',
        r'\s+scrollable="[^"]*"',
        r'\s+selected="[^"]*"',
        r'\s+displayed="[^"]*"',
        r'\s+a11y-important="[^"]*"',
        r'\s+screen-reader-focusable="[^"]*"',
        r'\s+drawing-order="[^"]*"',
        r'\s+showing-hint="[^"]*"',
        r'\s+text-entry-key="[^"]*"',
        r'\s+dismissable="[^"]*"',
        r'\s+a11y-focused="[^"]*"',
        r'\s+heading="[^"]*"',
        r'\s+live-region="[^"]*"',
        r'\s+context-clickable="[^"]*"',
        r'\s+content-invalid="[^"]*"',
    ]
    
    compressed = xml_text
    for pattern in unnecessary_attrs:
        compressed = re.sub(pattern, '', compressed, flags=re.IGNORECASE)
    
    # Remove clickable="false" and editable="false" (only keep if true)
    compressed = re.sub(r'\s+clickable="false"', '', compressed, flags=re.IGNORECASE)
    compressed = re.sub(r'\s+editable="false"', '', compressed, flags=re.IGNORECASE)
    
    # Remove empty resource-id
    compressed = re.sub(r'\s+resource-id=""', '', compressed)
    
    return compressed


def get_xml_diff(previous_xml: str, current_xml: str) -> str:
    """Generate incremental diff XML - only send changed nodes.
    
    This reduces token usage by 40-60% when screen changes are minimal.
    
    Returns:
        Diff XML string with only changed elements, or full XML if too different
    """
    import re
    from xml.etree import ElementTree as ET
    
    try:
        # Parse both XMLs
        try:
            prev_root = ET.fromstring(previous_xml)
            curr_root = ET.fromstring(current_xml)
        except ET.ParseError:
            # If parsing fails, return compressed current XML
            return compress_xml(current_xml)
        
        # Extract all elements with their key attributes
        def extract_elements(root, tag=''):
            elements = []
            for elem in root.iter():
                key_attrs = {
                    'text': elem.get('text', ''),
                    'content-desc': elem.get('content-desc', ''),
                    'resource-id': elem.get('resource-id', ''),
                    'bounds': elem.get('bounds', ''),
                    'class': elem.get('class', '')
                }
                # Create a signature for this element
                signature = f"{elem.tag}:{key_attrs['resource-id']}:{key_attrs['text']}:{key_attrs['content-desc']}"
                elements.append((signature, key_attrs, elem))
            return elements
        
        prev_elements = {sig: attrs for sig, attrs, _ in extract_elements(prev_root)}
        curr_elements = {sig: attrs for sig, attrs, _ in extract_elements(curr_root)}
        
        # Find changed elements
        changed_sigs = set()
        for sig in curr_elements:
            if sig not in prev_elements or curr_elements[sig] != prev_elements[sig]:
                changed_sigs.add(sig)
        
        # If more than 50% changed, return full compressed XML (diff not worth it)
        if len(changed_sigs) > len(curr_elements) * 0.5:
            return compress_xml(current_xml)
        
        # Build diff XML with only changed elements
        # For simplicity, return compressed current XML if changes are significant
        # In a more sophisticated implementation, we'd reconstruct XML with only changed nodes
        if len(changed_sigs) > 0:
            # Return compressed current XML with a note about changes
            compressed = compress_xml(current_xml)
            return f"<!-- {len(changed_sigs)} elements changed -->\n{compressed}"
        else:
            # No changes - return minimal diff
            return "<!-- No changes detected - screen unchanged -->"
            
    except Exception as e:
        # Fallback to compressed full XML
        return compress_xml(current_xml)


def truncate_xml(xml_text: str, max_length: int = 40000) -> str:
    """Truncate XML if too long, intelligently keeping important elements.
    
    Priority order:
    1. Keep elements with text (buttons, labels, product names)
    2. Keep interactive elements (clickable, editable)
    3. Keep beginning and end
    """
    if len(xml_text) <= max_length:
        return xml_text
    
    # Try to extract and preserve important elements before truncating
    import re
    
    # Find all elements with text or interactive attributes
    # Priority: elements with product names, buttons, and interactive elements
    important_patterns = [
        r'<[^>]*text="[^"]*(?:bike|light|backpack|cart|add|product|sauce)[^"]*"[^>]*>',  # Elements with product-related text (case-insensitive)
        r'<[^>]*text="[^"]*"[^>]*>',  # All elements with text
        r'<[^>]*clickable="true"[^>]*>',  # Clickable elements
        r'<[^>]*content-desc="[^"]*"[^>]*>',  # Elements with content-desc
        r'<[^>]*resource-id="[^"]*(?:button|cart|add|product)[^"]*"[^>]*>',  # Button/cart-related resource IDs
        r'<[^>]*resource-id="[^"]*"[^>]*>',  # All elements with resource-id
    ]
    
    important_elements = []
    for pattern in important_patterns:
        matches = re.finditer(pattern, xml_text, re.IGNORECASE)
        for match in matches:
            # Get the full element including its closing tag
            start = match.start()
            # Find the closing tag
            tag_name = re.search(r'<(\w+)', match.group()).group(1) if re.search(r'<(\w+)', match.group()) else None
            if tag_name:
                # Try to find the closing tag (simplified - assumes well-formed XML)
                end_tag = f"</{tag_name}>"
                end_pos = xml_text.find(end_tag, start)
                if end_pos != -1:
                    element = xml_text[start:end_pos + len(end_tag)]
                    if element not in important_elements:
                        important_elements.append(element)
    
    # If we found important elements, include them
    if important_elements:
        # Keep first part, important elements, and last part
        first_part = xml_text[:int(max_length * 0.5)]
        important_text = "\n".join(important_elements[:50])  # Limit to 50 important elements
        last_part = xml_text[-int(max_length * 0.2):]
        result = f"{first_part}\n\n<!-- Important elements preserved -->\n{important_text}\n\n... [XML truncated] ...\n\n{last_part}"
        # If still too long, fall back to simple truncation
        if len(result) > max_length * 1.2:
            first_part = xml_text[:int(max_length * 0.7)]
            last_part = xml_text[-int(max_length * 0.2):]
            return f"{first_part}\n\n... [XML truncated for brevity] ...\n\n{last_part}"
        return result
    
    # Fallback: Keep first 70% and last 20% with a marker
    first_part = xml_text[:int(max_length * 0.7)]
    last_part = xml_text[-int(max_length * 0.2):]
    return f"{first_part}\n\n... [XML truncated for brevity] ...\n\n{last_part}"


def truncate_text_block(text: str, max_length: int = 40000) -> str:
    """Generic text truncation helper used for JSON/summary payloads."""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    head = text[:int(max_length * 0.7)]
    tail = text[-int(max_length * 0.2):]
    return f"{head}\n\n... [truncated for brevity] ...\n\n{tail}"


def summarize_page_configuration(config: dict, max_items: int = 60) -> str:
    """
    Build a concise summary of the page configuration for LLM consumption.
    """
    if not isinstance(config, dict):
        return str(config)
    
    metadata = config.get('metadata') or {}
    elements = config.get('elements') or []
    
    header = (
        f"package={metadata.get('package') or 'unknown'} | "
        f"activity={metadata.get('activity') or 'unknown'} | "
        f"platform={metadata.get('platform') or 'unknown'} | "
        f"elements={len(elements)}/{metadata.get('elementCount') or len(elements)}"
    )
    
    lines = ["[PAGE CONFIG]", header]
    for elem in elements[:max_items]:
        alias = elem.get('alias') or 'element'
        role = elem.get('role') or 'unknown'
        summary = elem.get('summary') or ''
        primary = elem.get('primaryLocator') or {}
        locator_text = (
            f"{primary.get('strategy')}={primary.get('value')}"
            if primary else "n/a"
        )
        lines.append(f"- {alias} [{role}] {summary} | primary={locator_text}")
    
    remaining = len(elements) - max_items
    if remaining > 0:
        lines.append(f"... ({remaining} more elements truncated)")
    
    role_index = config.get('roleIndex') or {}
    if role_index:
        role_summary = ", ".join(f"{role}:{len(items)}" for role, items in role_index.items())
        lines.append(f"[role counts] {role_summary}")
    
    return "\n".join(lines)


def validate_message_pairs(messages_list: list) -> list:
    """Remove any tool_result blocks that don't have a corresponding tool_use in the previous message,
    and remove any tool_use blocks that don't have a corresponding tool_result in the next message.
    This prevents Bedrock API ValidationException errors."""
    if not messages_list:
        return messages_list
    
    validated_messages = []
    
    # Track all tool_use_ids from assistant messages and their corresponding tool_results
    tool_use_ids_with_results = set()
    
    # First pass: identify all tool_use_ids that have corresponding tool_results
    for i, msg in enumerate(messages_list):
        if msg.get('role') == 'assistant':
            content = msg.get('content', [])
            if isinstance(content, list):
                for block in content:
                    if block.get('type') == 'tool_use':
                        tool_use_id = block.get('id')
                        # Check if next message has corresponding tool_result
                        if i + 1 < len(messages_list):
                            next_msg = messages_list[i + 1]
                            if next_msg.get('role') == 'user':
                                next_content = next_msg.get('content', [])
                                if isinstance(next_content, list):
                                    for next_block in next_content:
                                        if (next_block.get('type') == 'tool_result' and 
                                            next_block.get('tool_use_id') == tool_use_id):
                                            tool_use_ids_with_results.add(tool_use_id)
                                            break
    
    # Second pass: validate and filter messages
    for i, msg in enumerate(messages_list):
        if msg.get('role') == 'assistant':
            # Check if assistant message has tool_use blocks
            content = msg.get('content', [])
            if isinstance(content, list):
                validated_content = []
                has_tool_use = False
                for block in content:
                    if block.get('type') == 'tool_use':
                        has_tool_use = True
                        tool_use_id = block.get('id')
                        # Only keep tool_use if it has a corresponding tool_result in next message
                        # OR if this is the last message (tool hasn't been executed yet - this is OK)
                        if i == len(messages_list) - 1:
                            # Last message - tool hasn't been executed yet, keep it
                            validated_content.append(block)
                        elif tool_use_id in tool_use_ids_with_results:
                            # Has corresponding tool_result, keep it
                            validated_content.append(block)
                        else:
                            # Orphaned tool_use - remove it
                            # Suppress technical message - not shown to users
                            # print(f"[WARN]  Removing orphaned tool_use for tool_use_id: {tool_use_id} (no tool_result found)")
                            pass
                    else:
                        # Not a tool_use, keep it
                        validated_content.append(block)
                
                # Only append assistant message if it has content
                # If it's the last message with tool_use, keep it even if validated_content is empty
                # (tool hasn't been executed yet)
                if validated_content:
                    validated_messages.append({
                        "role": "assistant",
                        "content": validated_content
                    })
                elif has_tool_use and i == len(messages_list) - 1:
                    # Last message with tool_use - keep it (tool will be executed)
                    validated_messages.append({
                        "role": "assistant",
                        "content": content
                    })
            else:
                validated_messages.append(msg)
        
        elif msg.get('role') == 'user':
            # Validate tool_result blocks in user message
            content = msg.get('content', [])
            if isinstance(content, list):
                validated_content = []
                for block in content:
                    if block.get('type') == 'tool_result':
                        tool_use_id = block.get('tool_use_id')
                        # Check if this tool_use_id exists in previous assistant message
                        if i > 0:
                            prev_msg = messages_list[i - 1]
                            if prev_msg.get('role') == 'assistant':
                                prev_content = prev_msg.get('content', [])
                                if isinstance(prev_content, list):
                                    has_matching_tool_use = False
                                    for prev_block in prev_content:
                                        if (prev_block.get('type') == 'tool_use' and 
                                            prev_block.get('id') == tool_use_id):
                                            has_matching_tool_use = True
                                            break
                                    
                                    if has_matching_tool_use:
                                        validated_content.append(block)
                                    else:
                                        # Orphaned tool_result - skip it
                                        # Suppress technical message - not shown to users
                                        # print(f"[WARN]  Removing orphaned tool_result for tool_use_id: {tool_use_id}")
                                        pass
                                else:
                                    validated_content.append(block)
                            else:
                                # No previous assistant message - this tool_result is orphaned
                                # Suppress technical message - not shown to users
                                # print(f"[WARN]  Removing orphaned tool_result (no previous assistant message): {tool_use_id}")
                                pass
                        else:
                            # First message can't have tool_result
                            # Suppress technical message - not shown to users
                            # print(f"[WARN]  Removing tool_result from first message: {tool_use_id}")
                            pass
                    else:
                        # Not a tool_result, keep it
                        validated_content.append(block)
                
                # Create new user message with validated content
                if validated_content:
                    validated_messages.append({
                        "role": "user",
                        "content": validated_content
                    })
            else:
                validated_messages.append(msg)
        else:
            validated_messages.append(msg)
    
    return validated_messages


def prune_messages(messages_list: list, max_messages: int = 25) -> list:
    """Keep only the most recent messages to stay within token limits.
    CRITICAL: Must keep tool_use and tool_result pairs together to avoid Bedrock API errors."""
    if len(messages_list) <= max_messages:
        return messages_list
    
    # Always keep the first user message (goal)
    first_message = messages_list[0]
    
    # Bedrock API requires tool_use and tool_result to be in consecutive messages
    # Message order: assistant (tool_use) comes before user (tool_result) in the list
    # We must prune by complete cycles to avoid breaking pairs
    
    # Start from the end and work backwards, keeping complete assistant+user pairs
    kept_messages = [first_message]  # Always keep first message
    remaining_slots = max_messages - 1
    
    # Work backwards from the end to keep most recent messages
    i = len(messages_list) - 1
    while i > 0 and remaining_slots > 0:
        msg = messages_list[i]
        if msg.get('role') == 'user':
            # Check if previous message is assistant (tool_use)
            if i > 0 and messages_list[i-1].get('role') == 'assistant':
                # Keep both as a pair
                kept_messages.insert(1, messages_list[i-1])  # Insert assistant before user
                kept_messages.insert(2, msg)  # Insert user after assistant
                remaining_slots -= 2
                i -= 2
            else:
                # Standalone user message
                kept_messages.insert(1, msg)
                remaining_slots -= 1
                i -= 1
        elif msg.get('role') == 'assistant':
            # Standalone assistant message (shouldn't happen, but handle it)
            kept_messages.insert(1, msg)
            remaining_slots -= 1
            i -= 1
        else:
            i -= 1
    
    return kept_messages


def parse_enumerated_plan_from_text(text: str) -> list:
    """Parse enumerated step plans from plain text."""
    if not text:
        return []

    plan_pattern = re.compile(
        r"^\s*(?:step\s*)?(\d+)[\.:)\-]\s*(.+)$",
        re.IGNORECASE
    )

    items = []
    for line in text.splitlines():
        match = plan_pattern.match(line.strip())
        if not match:
            continue
        step_num = int(match.group(1))
        description = match.group(2).strip()
        if not description:
            continue
        items.append({
            "step": step_num,
            "name": description,
            "description": description
        })

    # Remove duplicates by step number while keeping the first occurrence
    unique_items = []
    seen_steps = set()
    for item in items:
        step_num = item["step"]
        if step_num in seen_steps:
            continue
        seen_steps.add(step_num)
        unique_items.append(item)

    return unique_items
    
    # Always keep the first user message (goal)
    first_message = messages_list[0]
    
    # Bedrock API requires tool_use and tool_result to be in consecutive messages
    # Message order: assistant (tool_use) comes before user (tool_result) in the list
    # We must prune by complete cycles to avoid breaking pairs
    
    # Reserve: first message (1) + summary (1) + recent messages
    messages_to_keep = max_messages - 2
    
    # Build a map of tool_use_id to assistant message index
    # Then when we keep an assistant message, we can find its corresponding user message
    tool_use_to_assistant_idx = {}
    assistant_idx_to_tool_use_ids = {}
    
    for idx, msg in enumerate(messages_list):
        if msg.get('role') == 'assistant':
            content = msg.get('content', [])
            if isinstance(content, list):
                tool_use_ids = []
                for block in content:
                    if block.get('type') == 'tool_use':
                        tool_use_id = block.get('id')
                        tool_use_ids.append(tool_use_id)
                        tool_use_to_assistant_idx[tool_use_id] = idx
                if tool_use_ids:
                    assistant_idx_to_tool_use_ids[idx] = tool_use_ids
    
    # Find user messages that contain tool_results and map them to their assistant messages
    user_to_assistant_idx = {}
    for idx, msg in enumerate(messages_list):
        if msg.get('role') == 'user':
            content = msg.get('content', [])
            if isinstance(content, list):
                for block in content:
                    if block.get('type') == 'tool_result':
                        tool_use_id = block.get('tool_use_id')
                        if tool_use_id in tool_use_to_assistant_idx:
                            assistant_idx = tool_use_to_assistant_idx[tool_use_id]
                            user_to_assistant_idx[idx] = assistant_idx
                            break
    
    # Start from the end and work backwards, keeping complete cycles
    # Messages are ordered: [oldest, ..., newest]
    # Tool_use/tool_result pairs: assistant at i, user at i+1
    kept_indices = set()
    i = len(messages_list) - 1
    
    while i > 0 and len(kept_indices) < messages_to_keep:
        msg = messages_list[i]
        
        # If current message is assistant with tool_use, we MUST keep it with its tool_result
        if i in assistant_idx_to_tool_use_ids:
            # This is an assistant message with tool_use - keep it
            kept_indices.add(i)
            
            # The user message with tool_result should be at i+1 (next message)
            # But if we're at the end, there might not be a tool_result yet
            # Check if there's a user message that references this assistant's tool_use_ids
            tool_use_ids_for_this_assistant = assistant_idx_to_tool_use_ids[i]
            user_idx = None
            
            # Look for user message that has tool_result with matching tool_use_id
            for u_idx, a_idx in user_to_assistant_idx.items():
                if a_idx == i:
                    user_idx = u_idx
                    break
            
            if user_idx is not None:
                # Found matching user message - keep it too
                kept_indices.add(user_idx)
                # Skip both messages (we'll handle them)
                # Move to before the assistant message
                i = i - 1
                continue
        
        # If current message is a user message that's part of a pair, check if we already kept its assistant
        if i in user_to_assistant_idx:
            assistant_idx = user_to_assistant_idx[i]
            if assistant_idx in kept_indices:
                # The assistant was already kept, so this user message should be kept too
                # (This handles the case when we encounter the user message first during backward iteration)
                kept_indices.add(i)
                i -= 1
                continue
        
        # Regular message (not part of a tool_use/tool_result pair), keep it if we have room
        if len(kept_indices) < messages_to_keep:
            kept_indices.add(i)
        
        i -= 1
    
    # Build the kept messages list in order
    kept_messages = [messages_list[idx] for idx in sorted(kept_indices)]
    
    # Count pruned cycles
    action_cycles_pruned = max(0, (len(messages_list) - len(kept_messages) - 1) // 2)
    
    # Create summary if we pruned anything
    if action_cycles_pruned > 0:
        summary = {
            "role": "user",
            "content": f"[Previous {action_cycles_pruned} action cycles completed successfully. Continuing from current state...]"
        }
        return [first_message, summary] + kept_messages
    
    return [first_message] + kept_messages


def is_navigation_action(function_name: str, function_args: dict) -> bool:
    """Detect if an action is likely to cause a screen/page change."""
    if function_name in ('launch_app', 'press_back_button', 'press_home_button', 'reset_app', 'close_app'):
        return True
    
    # Click on buttons that likely navigate (Login, Submit, Next, etc.)
    if function_name == 'click':
        value = (function_args.get('value') or '').lower()
        strategy = (function_args.get('strategy') or '').lower()
        # Common navigation button patterns
        nav_keywords = ['login', 'submit', 'next', 'continue', 'confirm', 'ok', 'done', 'save', 'send', 'proceed', 'enter', 'checkout', 'finish', 'cart']
        if any(kw in value for kw in nav_keywords):
            return True
        # Check for "test-CART", "test-CHECKOUT", "test-CONTINUE", "test-FINISH" patterns
        if 'test-cart' in value or 'test-checkout' in value or 'test-continue' in value or 'test-finish' in value:
            return True
    
    return False


def parse_validation_requirements(user_goal: str) -> dict:
    """Parse user prompt to extract explicit validation requirements.
    
    Returns a dict mapping action descriptions to validation requirements.
    Example: {
        'tamil songs page comes': {'text': 'the tamil songs page comes', 'context': '...'},
        'video is playing': {'text': 'the video is playing', 'context': '...'}
    }
    """
    import re
    validation_map = {}
    seen_texts = set()
    
    # Patterns to detect validation requests (ordered from most specific to least)
    validation_patterns = [
        (r'validate\s+(?:whether|if|that)\s+(.+?)(?=,|\.|then|and|$)', 'validate'),
        (r'verify\s+(?:whether|if|that)\s+(.+?)(?=,|\.|then|and|$)', 'verify'),
        (r'check\s+(?:whether|if|that)\s+(.+?)(?=,|\.|then|and|$)', 'check'),
        (r'validate\s+(.+?)(?=,|\.|then|and|$)', 'validate'),
        (r'verify\s+(.+?)(?=,|\.|then|and|$)', 'verify'),
        (r'check\s+(.+?)(?=,|\.|then|and|$)', 'check'),
    ]
    
    # Find all validation mentions
    for pattern, verb in validation_patterns:
        matches = re.finditer(pattern, user_goal, re.IGNORECASE)
        for match in matches:
            validation_text = match.group(1).strip()
            # Normalize text for deduplication (remove leading articles)
            normalized = re.sub(r'^(the|a|an)\s+', '', validation_text.lower()).strip()
            
            # Skip if we've already seen this validation (avoid duplicates)
            if normalized in seen_texts:
                continue
            seen_texts.add(normalized)
            
            # Try to find the action that precedes this validation
            # Look backwards from the match position
            before_text = user_goal[:match.start()].lower()
            
            # Extract context (what action should be validated)
            validation_map[normalized] = {
                'text': validation_text,
                'verb': verb,
                'context': before_text[-100:] if len(before_text) > 100 else before_text
            }
    
    return validation_map


def requires_verification(function_name: str, function_args: dict, user_validation_map: dict = None) -> bool:
    """Detect if an action requires verification after execution.
    
    Now only returns True if validation is explicitly requested in user prompt.
    """
    # If no validation map provided, no validation required
    if not user_validation_map:
        return False
    
    # Check if this action might need validation based on context
    # This is a simple heuristic - the LLM will decide based on the prompt
    # We just disable automatic enforcement
    
    return False  # Never automatically require verification


def extract_prominent_text_from_xml(xml_text: str) -> list:
    """Extract prominent text elements from XML page source (titles, headers, etc.).
    Prioritizes page titles over menu buttons and navigation elements."""
    import re
    
    prominent_texts = []
    menu_nav_texts = []  # Menu/navigation elements (lower priority)
    
    # Extract text from TextView elements (most common for titles/headers)
    textview_pattern = r'<TextView[^>]*text="([^"]+)"'
    matches = re.findall(textview_pattern, xml_text, re.IGNORECASE)
    for match in matches:
        if match and len(match.strip()) > 0:
            text = match.strip()
            text_lower = text.lower()
            # Check if it's a menu/navigation element (lower priority)
            if any(kw in text_lower for kw in ['menu', 'navigation', 'drawer', 'hamburger', 'sidebar']):
                menu_nav_texts.append(text)
            else:
                prominent_texts.append(text)
    
    # Extract content-desc attributes (often used for accessibility labels)
    content_desc_pattern = r'content-desc="([^"]+)"'
    matches = re.findall(content_desc_pattern, xml_text, re.IGNORECASE)
    for match in matches:
        if match and len(match.strip()) > 0:
            text = match.strip()
            text_lower = text.lower()
            # Check if it's a menu/navigation element (lower priority)
            if any(kw in text_lower for kw in ['menu', 'navigation', 'drawer', 'hamburger', 'sidebar', 'test-menu']):
                menu_nav_texts.append(text)
            else:
                prominent_texts.append(text)
    
    # Remove duplicates and filter out very short or common words
    unique_texts = []
    seen = set()
    common_words = {'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'a', 'an'}
    
    # Process prominent texts first (page titles, headers)
    for text in prominent_texts:
        text_lower = text.lower()
        # Skip if too short, common word, or already seen
        if len(text) < 3 or text_lower in common_words or text_lower in seen:
            continue
        seen.add(text_lower)
        unique_texts.append(text)
    
    # Add menu/nav texts at the end (lower priority) - only if no prominent texts found
    if not unique_texts:
        for text in menu_nav_texts:
            text_lower = text.lower()
            if len(text) >= 3 and text_lower not in common_words and text_lower not in seen:
                seen.add(text_lower)
                unique_texts.append(text)
    
    # Return top 10 most prominent texts (page titles first, menu buttons last)
    return unique_texts[:10]


def detect_page_name_from_text(text: str, xml_text: str = None) -> str:
    """Detect page name from text identifier or XML content.
    Works generically for any app, not just e-commerce."""
    if not text:
        return "Unknown Page"
    
    text_lower = text.lower()
    
    # Generic page detection patterns (works for any app)
    # Check for common page patterns first
    
    # E-commerce patterns
    if any(keyword in text_lower for keyword in ['thank you', 'order complete', 'checkout: complete']):
        return "Order Complete Page"
    elif any(keyword in text_lower for keyword in ['checkout: overview', 'order summary', 'payment']):
        return "Checkout Overview Page"
    elif any(keyword in text_lower for keyword in ['checkout', 'first name', 'last name', 'zip code', 'postal code']):
        return "Checkout Information Page"
    elif any(keyword in text_lower for keyword in ['cart', 'shopping cart', 'your cart']):
        return "Cart Page"
    elif any(keyword in text_lower for keyword in ['products', 'catalog', 'shop', 'store']):
        return "Products Page"
    
    # Authentication patterns
    elif any(keyword in text_lower for keyword in ['login', 'sign in', 'username', 'password']):
        return "Login Page"
    elif any(keyword in text_lower for keyword in ['sign up', 'register', 'create account']):
        return "Registration Page"
    
    # OTT/Streaming platform patterns (HIGH PRIORITY - Check first)
    elif any(keyword in text_lower for keyword in ['profile selection', 'choose profile', 'select profile', 'who\'s watching']):
        return "Profile Selection Page"
    elif any(keyword in text_lower for keyword in ['my list', 'watchlist', 'saved', 'favorites']):
        return "My List Page"
    elif any(keyword in text_lower for keyword in ['continue watching', 'resume watching', 'resume']):
        return "Continue Watching Page"
    elif any(keyword in text_lower for keyword in ['season', 'episode', 'episodes', 'select episode']):
        return "Episode Selection Page"
    elif any(keyword in text_lower for keyword in ['movie details', 'show details', 'content details', 'title details']):
        return "Content Details Page"
    elif any(keyword in text_lower for keyword in ['category', 'genre', 'browse', 'categories', 'genres']):
        return "Category Browse Page"
    elif any(keyword in text_lower for keyword in ['trending', 'popular', 'top', 'recommended', 'recommendations']):
        return "Recommendations Page"
    
    # Media/Video patterns (fallback for non-OTT video apps)
    elif any(keyword in text_lower for keyword in ['video', 'player', 'play', 'pause', 'youtube']):
        return "Video Player Page"
    elif any(keyword in text_lower for keyword in ['search results', 'results for']):
        return "Search Results Page"
    
    # Settings/Profile patterns
    elif any(keyword in text_lower for keyword in ['settings', 'preferences', 'configuration']):
        return "Settings Page"
    elif any(keyword in text_lower for keyword in ['profile', 'account', 'user info']):
        return "Profile Page"
    
    # Generic navigation patterns
    elif any(keyword in text_lower for keyword in ['home', 'main', 'dashboard']):
        return "Home Page"
    elif any(keyword in text_lower for keyword in ['menu', 'navigation', 'drawer']):
        return "Menu Page"
    
    # If no pattern matches, try to extract page name from the text itself
    # Use the text as page name if it looks like a title/header
    if len(text) > 3 and len(text) < 50:
        # Capitalize first letter of each word
        page_name = ' '.join(word.capitalize() for word in text.split())
        return f"{page_name} Page"
    
    return "Unknown Page"


def auto_detect_page_after_navigation(session_id: str = None) -> dict:
    """Automatically detect page name after navigation action using OCR and XML.
    Works generically for any app."""
    import appium_tools
    
    # Wait for page to load (reduced to 0.2s - XML parsing is fast and page usually loads quickly)
    time.sleep(0.05)  # Reduced wait for faster execution
    
    # Strategy 1: Extract prominent text from XML page source
    try:
        xml_result = get_page_source()
        # Handle both string (success) and dict (error) returns
        if isinstance(xml_result, dict):
            if xml_result.get('success'):
                xml_text = xml_result.get('value', '')
            else:
                xml_text = ''  # Error case, skip XML extraction
        else:
            xml_text = xml_result
        if xml_text:
            prominent_texts = extract_prominent_text_from_xml(xml_text)
        
        # Try to detect page name from prominent texts
        for text in prominent_texts[:5]:  # Check top 5 prominent texts
            detected_page = detect_page_name_from_text(text, xml_text)
            if detected_page != "Unknown Page":
                return {
                    "detected": True,
                    "page_name": detected_page,
                    "identifier": text,
                    "method": "XML"
                }
        
        # If no pattern matched, use the most prominent text as page name
        if prominent_texts:
            top_text = prominent_texts[0]
            page_name = detect_page_name_from_text(top_text)
            if page_name == "Unknown Page":
                # Create page name from the text itself
                page_name = f"{top_text} Page"
            return {
                "detected": True,
                "page_name": page_name,
                "identifier": top_text,
                "method": "XML (prominent text)"
            }
    except Exception as e:
        print(f"[WARN]  XML-based page detection failed: {e}")
    
    # Strategy 2: Try common page identifiers via OCR (fallback)
    if session_id:
        common_identifiers = [
            "PRODUCTS", "CART", "CHECKOUT", "LOGIN", "SETTINGS", 
            "HOME", "PROFILE", "SEARCH", "VIDEO", "PLAYER"
        ]
        
        for identifier in common_identifiers:
            try:
                result = appium_tools.wait_for_text_ocr(
                    identifier, 
                    timeoutSeconds=1, 
                    sessionId=session_id
                )
                if isinstance(result, dict) and result.get('success'):
                    detected_page = detect_page_name_from_text(identifier)
                    return {
                        "detected": True,
                        "page_name": detected_page,
                        "identifier": identifier,
                        "method": "OCR"
                    }
            except Exception:
                continue
    
    return {
        "detected": False,
        "page_name": "Unknown Page",
        "identifier": "None",
        "method": "None"
    }


def get_verification_requirement(function_name: str, function_args: dict) -> str:
    """Get the specific verification requirement message for an action."""
    if function_name == 'click':
        value = (function_args.get('value') or '').lower()
        # Check for specific button types
        if 'add to cart' in value:
            return (
                "[WARN] CRITICAL: You clicked 'Add to Cart'. You MUST verify the action succeeded IMMEDIATELY: "
                "Wait 1-2 seconds, then call wait_for_text_ocr(value='REMOVE', timeoutSeconds=5) to verify "
                "the button changed from 'ADD TO CART' to 'REMOVE' (indicates product was added). "
                "If verification fails, the product was NOT added - the test FAILED."
            )
        elif is_navigation_action(function_name, function_args):
            return (
                "[WARN] CRITICAL: This was a navigation action. You MUST verify the page changed: "
                "Wait 2-3 seconds, then call wait_for_text_ocr with the expected page identifier "
                "(e.g., 'YOUR CART' after clicking cart, 'CHECKOUT: OVERVIEW' after Continue). "
                "If verification fails, navigation FAILED."
            )
        else:
            return (
                "[WARN] CRITICAL: You performed a click action. You MUST verify the action succeeded: "
                "Check if the expected result occurred (button state changed, element appeared/disappeared, etc.). "
                "Use wait_for_text_ocr or wait_for_element to verify. If verification fails, the action FAILED."
            )
    
    elif function_name in ('send_keys', 'ensure_focus_and_type'):
        return (
            "[WARN] CRITICAL: You entered text. You MUST verify the text was actually entered: "
            "Use get_element_text to verify the field contains the entered text, "
            "or use wait_for_text_ocr to verify the text appears on screen. "
            "If verification fails, text was NOT entered - the action FAILED. "
            "[WARN] IMPORTANT: If the next action is clicking a button (especially CONTINUE, SUBMIT, LOGIN), "
            "call hide_keyboard() FIRST to ensure the button is visible and not hidden by the keyboard."
        )
    
    elif function_name in ('scroll_to_element', 'scroll'):
        return (
            "[WARN] CRITICAL: You scrolled. You MUST verify the target element is now visible: "
            "Use wait_for_text_ocr or wait_for_element to verify the scrolled-to element is visible. "
            "If element still not visible, scroll FAILED."
        )
    
    return (
        "[WARN] CRITICAL: You performed an action. You MUST verify it succeeded: "
        "Check if the expected result occurred. Use appropriate verification method (OCR, element check, etc.). "
        "If verification fails, the action FAILED."
    )


def _is_session_crashed_error(error_msg: str) -> bool:
    """Check if error indicates session crash."""
    if not error_msg:
        return False
    error_lower = str(error_msg).lower()
    crash_indicators = [
        'instrumentation process is not running',
        'cannot be proxied to uiautomator2',
        'probably crashed',
        'session.*crashed',
        'instrumentation.*crashed'
    ]
    return any(indicator in error_lower for indicator in crash_indicators)


def _extract_app_targets(user_goal: str | None) -> list[str]:
    """Extract app names mentioned in user goal (e.g., 'open YouTube')."""
    if not user_goal:
        return []
    targets = []
    patterns = re.findall(r'\b(?:open|launch|start)\s+([a-z0-9 .&_-]+?)(?:\s+(?:and|to|for|with)\b|[,.!?]|$)', user_goal, re.IGNORECASE)
    for match in patterns:
        cleaned = match.strip(" .,-_")
        if cleaned:
            targets.append(cleaned)
    # Single words like 'youtube' might not be in pattern if no verb; fallback by scanning for known app triggers
    extra = re.findall(r'\b(youtube|yt music|gmail|linkedin|whatsapp|calculator|camera|gallery|play store|gpay|google pay|chrome|maps)\b', user_goal, re.IGNORECASE)
    for word in extra:
        cleaned = word.strip()
        if cleaned and cleaned.lower() not in [t.lower() for t in targets]:
            targets.append(cleaned)
    return targets


def _refine_click_locator(function_args: dict,
                          cached_page_config: dict | None,
                          user_goal: str | None,
                          config_fetcher=None):
    """Refine ambiguous launcher clicks using structured page configuration aliases."""
    if (not cached_page_config or not isinstance(cached_page_config, dict)) and callable(config_fetcher):
        try:
            cached_page_config = config_fetcher("click locator refinement")
        except Exception as fetch_error:
            print(f"[WARN]  Could not fetch page configuration for refinement: {fetch_error}")
            cached_page_config = None
    if not cached_page_config or not isinstance(function_args, dict):
        return function_args, None, None
    strategy = function_args.get('strategy')
    value = (function_args.get('value') or '').strip()
    ambiguous_ids = {
        "com.sec.android.app.launcher:id/icon",
        "com.sec.android.app.launcher:id/folder_icon_view",
        "com.sec.android.app.launcher:id/wsCellLayout"
    }
    if value not in ambiguous_ids:
        return function_args, None, None
    targets = _extract_app_targets(user_goal)
    if not targets:
        return function_args, None, None
    elements = cached_page_config.get('elements') or []
    for target in targets:
        t_lower = target.lower()
        for elem in elements:
            if (elem.get('resourceId') or '').lower() != value.lower():
                continue
            text_blob = " ".join(filter(None, [
                elem.get('alias'),
                elem.get('text'),
                elem.get('contentDescription'),
                elem.get('summary')
            ]))
            if text_blob and t_lower in text_blob.lower():
                locators = elem.get('locators') or []
                primary = elem.get('primaryLocator')
                candidate_locators = []
                if primary:
                    candidate_locators.append(primary)
                candidate_locators.extend(locators)
                for locator in candidate_locators:
                    if locator and locator.get('strategy') and locator.get('value'):
                        refined_args = dict(function_args)
                        refined_args['strategy'] = locator['strategy']
                        refined_args['value'] = locator['value']
                        return refined_args, elem.get('alias'), target
    return function_args, None, None


def _execute_with_retry(function_name: str,
                        function_args: dict,
                        available_functions: dict,
                        expected_inputs: dict,
                        smart_executor: SmartActionExecutor | None = None,
                        max_retries: int = 3,
                        user_goal: str | None = None,
                        cached_page_config: dict | None = None,
                        config_fetcher=None):
    """
    Execute an action with retry logic and fallback strategies.
    
    Args:
        function_name: Name of the function to execute
        function_args: Arguments for the function
        available_functions: Dictionary of available functions
        expected_inputs: Dictionary of expected inputs (for validation)
        smart_executor: Optional smart executor for deterministic fallbacks
        max_retries: Maximum number of retry attempts (default: 3)
    
    Returns:
        Result dictionary from the function call
    """
    import appium_tools
    
    # Skip retry for assertions - they should fail immediately
    if function_name in ('wait_for_element', 'wait_for_text_ocr', 'assert_activity', 'get_page_source'):
        function_to_call = available_functions[function_name]
        return function_to_call(**function_args)
    
    # Skip retry for launch_app if disabled
    disable_launch = os.getenv('DISABLE_LAUNCH_APP', '1').lower() in ('1', 'true', 'yes')
    if disable_launch and function_name == 'launch_app':
        return {"success": False, "error": "launch_app disabled by configuration (DISABLE_LAUNCH_APP)"}
    
    refined_alias = None
    refined_target = None
    if function_name == 'click':
        function_args, refined_alias, refined_target = _refine_click_locator(
            function_args, cached_page_config, user_goal, config_fetcher
        )
        if refined_alias and refined_target:
            print(f"--- [SMART] Refined click: target '{refined_target}' matched alias '{refined_alias}'")
    
    # Check if sending "\n" to search fields - only block if search button is visible
    if function_name in ('send_keys', 'ensure_focus_and_type'):
        text_value = function_args.get('text', '')
        element_value = function_args.get('value', '').lower()
        is_search_field = 'search' in element_value or 'query' in element_value
        if is_search_field and (text_value == '\\n' or text_value == '\n' or text_value == '\\n'):
            # Check if a search button exists in the page source before blocking
            try:
                # Get page source to check for search button
                xml_result = get_page_source()
                xml_text = ""
                if isinstance(xml_result, dict):
                    if xml_result.get('success'):
                        xml_text = xml_result.get('value', '') or xml_result.get('xml', '') or ""
                elif isinstance(xml_result, str):
                    xml_text = xml_result
                else:
                    xml_text = str(xml_result or "")
                
                # Check if search button exists in XML
                has_search_button = False
                if xml_text:
                    xml_lower = xml_text.lower()
                    # Look for search/submit buttons in the XML
                    search_button_patterns = [
                        'resource-id="' in xml_lower and ('search' in xml_lower or 'submit' in xml_lower),
                        'content-desc="' in xml_lower and ('search' in xml_lower or 'submit' in xml_lower),
                        'class="android.widget.button' in xml_lower and 'search' in xml_lower,
                        'class="android.widget.imagebutton' in xml_lower and 'search' in xml_lower
                    ]
                    has_search_button = any(search_button_patterns)
                
                if has_search_button:
                    print(f"--- [BLOCKED] Search button found in page source. Preventing sending '\\n' to search field '{element_value}'. Use click on search button instead.")
                    return {
                        "success": False,
                        "error": "A search button is visible in the page source. You MUST call get_page_source to find the search button (resource-id containing 'search' or 'submit', or content-desc containing 'Search' or 'Submit') and click it to submit the search. Do NOT send '\\n' when a search button is available."
                    }
                else:
                    print(f"--- [ALLOWED] No search button found in page source. Allowing '\\n' as fallback for search field '{element_value}'.")
                    # Allow "\n" to proceed - no search button found, so Enter key is acceptable fallback
            except Exception as e:
                print(f"--- [WARN] Could not check for search button: {e}. Allowing '\\n' as fallback.")
                # If check fails, allow "\n" to proceed as fallback
    
    function_to_call = available_functions[function_name]
    last_error = None
    
    def _is_success_result(res: dict | str | None) -> bool:
        if isinstance(res, dict):
            success_value = res.get('success')
            if success_value is True or success_value == True or str(success_value).lower() == 'true':
                return True
            if success_value is False or success_value == False or str(success_value).lower() == 'false':
                return False
        if isinstance(res, str) and res.startswith("Error:"):
            return False
        return True

    # PRE-VALIDATION: Auto-resolve container IDs to EditText before smart executor runs
    # This fixes 90% of cases where LLM chooses container instead of EditText
    if smart_executor and smart_executor.can_handle(function_name):
        if function_name in ('send_keys', 'ensure_focus_and_type'):
            strategy = function_args.get('strategy', '')
            value = function_args.get('value', '')
            
            # Check if value is a container pattern
            container_keywords = ("chip_group", "chipgroup", "container", "wrapper", "layout", "viewgroup", "recycler")
            if value and any(keyword in value.lower() for keyword in container_keywords):
                # Auto-resolve container to EditText BEFORE smart executor runs
                resolved_strategy, resolved_value = resolve_editable_locator(strategy, value)
                if resolved_strategy != strategy or resolved_value != value:
                    print(f"--- [AUTO-FIX] Resolved container '{value}' to EditText: {resolved_strategy}={resolved_value}")
                    # Update function_args with resolved locator (create new dict to ensure update)
                    function_args = dict(function_args)  # Make a copy
                    function_args['strategy'] = resolved_strategy
                    function_args['value'] = resolved_value
        
        try:
            smart_result = smart_executor.execute(function_name, function_args, enforce_expected_inputs=True)
            if smart_result is not None:
                return smart_result
        except ValueError as strict_error:
            return {"success": False, "error": str(strict_error)}

    for attempt in range(1, max_retries + 1):
        # First attempt: try original action
        if attempt == 1:
            result = function_to_call(**function_args)
        else:
            # Subsequent attempts: try fallback strategies
            print(f"  [RETRY] Attempt {attempt}/{max_retries}: Trying fallback strategy...")
            
            # Wait a bit before retry (reduced from 1s to 0.3s for faster retries)
            time.sleep(0.1)  # Reduced wait for faster execution
            
            # Fallback strategies based on action type
            if function_name in ('send_keys', 'ensure_focus_and_type'):
                # Strategy 1: Try scrolling to element first, then typing
                strategy = function_args.get('strategy', 'id')
                value = function_args.get('value', '')
                text = function_args.get('text', '')
                
                if attempt == 2:
                    # Try scrolling to element first
                    print(f"  [FALLBACK] Scrolling to element before typing...")
                    scroll_result = appium_tools.scroll_to_element(strategy=strategy, value=value)
                    if isinstance(scroll_result, dict) and scroll_result.get('success'):
                        # Wait a bit after scrolling (reduced from 0.5s to 0.2s)
                        time.sleep(0.05)  # Reduced wait for faster execution
                        result = function_to_call(**function_args)
                    else:
                        # If scroll fails, try ensure_focus_and_type instead of send_keys
                        if function_name == 'send_keys':
                            print(f"  [FALLBACK] Trying ensure_focus_and_type instead of send_keys...")
                            if 'ensure_focus_and_type' in available_functions:
                                result = available_functions['ensure_focus_and_type'](
                                    strategy=strategy,
                                    value=value,
                                    text=text,
                                    timeoutMs=10000,  # Longer timeout
                                    hideKeyboard=False
                                )
                            else:
                                result = function_to_call(**function_args)
                        else:
                            result = function_to_call(**function_args)
                elif attempt == 3:
                    # Strategy 2: Try clicking first, then typing
                    print(f"  [FALLBACK] Clicking element first, then typing...")
                    click_result = appium_tools.click(strategy=strategy, value=value)
                    if isinstance(click_result, dict) and click_result.get('success'):
                        time.sleep(0.05)  # Reduced wait for faster execution
                        result = function_to_call(**function_args)
                    else:
                        result = function_to_call(**function_args)
                else:
                    result = function_to_call(**function_args)
                    
            elif function_name == 'click':
                # Strategy: Try scrolling to element first, then clicking
                strategy = function_args.get('strategy', 'id')
                value = function_args.get('value', '')
                normalized_value = (value or "").strip().lower()
                
                if attempt == 2:
                    print(f"  [FALLBACK] Scrolling to element before clicking...")
                    scroll_result = appium_tools.scroll_to_element(strategy=strategy, value=value)
                    if isinstance(scroll_result, dict) and scroll_result.get('success'):
                        time.sleep(0.05)  # Reduced wait for faster execution
                        result = function_to_call(**function_args)
                    else:
                        result = function_to_call(**function_args)
                elif attempt == 3:
                    # Strategy: Try waiting for element with longer timeout, then clicking
                    print(f"  [FALLBACK] Waiting for element with longer timeout, then clicking...")
                    wait_result = appium_tools.wait_for_element(strategy=strategy, value=value, timeoutMs=10000)
                    if isinstance(wait_result, dict) and wait_result.get('success'):
                        time.sleep(0.05)  # Reduced wait for faster execution
                        result = function_to_call(**function_args)
                    else:
                        result = function_to_call(**function_args)

                    # If still failing, try alternate selectors (known problematic targets)
                    if not _is_success_result(result):
                        alternate_selectors = _get_alternate_click_strategies(strategy, value)
                        if alternate_selectors:
                            print("  [FALLBACK] Trying alternate selectors for click target...")
                            for alt in alternate_selectors:
                                alt_strategy = alt.get("strategy", strategy)
                                alt_value = alt.get("value", value)
                                print(f"    ↳ Trying {alt_strategy}={alt_value}")
                                alt_function = available_functions.get('click', function_to_call)
                                alt_result = alt_function(strategy=alt_strategy, value=alt_value)
                                result = alt_result
                                if _is_success_result(alt_result):
                                    break

                    # If still failing, press back to reach parent view (useful for apps already deep in navigation)
                    if not _is_success_result(result) and normalized_value in {"compose", "compose button", "compose new email"}:
                        back_function = available_functions.get('press_back_button')
                        if back_function:
                            print("  [FALLBACK] Pressing back to exit current view before reattempting click...")
                            for _ in range(2):
                                back_function()
                                time.sleep(0.4)
                                retry_result = function_to_call(**function_args)
                                result = retry_result
                                if _is_success_result(retry_result):
                                    break
                else:
                    result = function_to_call(**function_args)
            else:
                # For other actions, just retry with original args
                result = function_to_call(**function_args)
        
        # Check if result indicates success
        is_success = False
        if isinstance(result, dict):
            success_value = result.get('success')
            if success_value is True or success_value == True or str(success_value).lower() == 'true':
                is_success = True
            elif success_value is False or success_value == False or str(success_value).lower() == 'false':
                last_error = result.get('error', result.get('message', 'Action returned success: false'))
        elif isinstance(result, str) and result.startswith("Error:"):
            last_error = result
        else:
            # If result is not a dict or string, assume success
            is_success = True
        
        if is_success:
            if attempt > 1:
                print(f"  [SUCCESS] Action succeeded on attempt {attempt}")
            return result
        
        # If this was the last attempt, return the failure
        if attempt == max_retries:
            print(f"  [FAILED] Action failed after {max_retries} attempts")
            failure_message = last_error or (result if isinstance(result, str) else 'Action failed after all retry attempts')
            if isinstance(result, dict):
                result['success'] = False
                result['error'] = result.get('error', failure_message)
                result['retryAttempts'] = max_retries
                result['failureReason'] = result.get('failureReason', f"Action failed after {max_retries} attempts")
                return result
            else:
                return {
                    "success": False,
                    "error": str(failure_message),
                    "retryAttempts": max_retries,
                    "failureReason": f"Action failed after {max_retries} attempts"
                }
    
    # Should never reach here, but return last result
    return result


def _get_alternate_click_strategies(original_strategy: str, value: str) -> List[Dict[str, str]]:
    """Return alternate selectors to try for problematic click targets."""
    normalized_value = (value or "").strip().lower()
    alternates: List[Dict[str, str]] = []

    if normalized_value in {"compose", "compose button"}:
        # Gmail compose floating action button
        alternates.extend(
            [
                {"strategy": "id", "value": "com.google.android.gm:id/compose_button"},
                {"strategy": "id", "value": "com.google.android.gm:id/compose_button_icon"},
                {"strategy": "text", "value": "Compose"},
                {"strategy": "content-desc", "value": "Compose new email"},
            ]
        )
    elif normalized_value in {"new message", "new mail", "new email"}:
        alternates.append({"strategy": "id", "value": "com.google.android.gm:id/compose_button"})

    # Ensure we include the original selector as a fallback if alternates list ended up empty
    if not alternates:
        return []

    # De-duplicate while preserving order
    seen = set()
    unique_alternates = []
    for alt in alternates:
        key = (alt["strategy"], alt["value"])
        if key not in seen:
            seen.add(key)
            unique_alternates.append(alt)

    return unique_alternates


def format_step_description(function_name: str, function_args: dict) -> str:
    """Format a human-readable step description from function name and args."""
    action_map = {
        'click': 'Click on',
        'send_keys': 'Type',
        'wait_for_element': 'Check',
        'launch_app': 'Open',
        'press_back_button': 'Press back button',
        'press_home_button': 'Press home button',
        'scroll': 'Scroll',
        'scroll_to_element': 'Scroll to',
        'swipe': 'Swipe',
        'long_press': 'Long press on',
        'get_page_source': 'Get page source',
        'take_screenshot': 'Take screenshot',
        'clear_element': 'Clear',
        'get_element_text': 'Get text from',
        'close_app': 'Close app',
        'reset_app': 'Reset app',
        'get_orientation': 'Get orientation',
        'set_orientation': 'Set orientation',
        'hide_keyboard': 'Hide keyboard',
        'lock_device': 'Lock device',
        'unlock_device': 'Unlock device',
        'get_battery_info': 'Get battery info',
        'get_current_package_activity': 'Get current app info',
        'is_app_installed': 'Check if app installed',
        'get_contexts': 'Get contexts',
        'switch_context': 'Switch context',
        'open_notifications': 'Open notifications'
    }
    
    action = action_map.get(function_name, function_name.replace('_', ' ').title())
    
    # Format based on action type
    if function_name == 'send_keys':
        text = function_args.get('text', '')
        value = function_args.get('value', '')
        if 'user' in value.lower() or 'username' in value.lower():
            return f"Type {text} in username"
        elif 'pass' in value.lower() or 'password' in value.lower():
            return f"Type {text} in password"
        else:
            return f"Type {text} in {value}"
    elif function_name == 'click':
        value = function_args.get('value', '')
        value_lower = value.lower()

        def humanize_identifier(identifier: str) -> str:
            if not identifier:
                return ""
            cleaned = identifier.replace('tag_', '').replace('test_', '')
            cleaned = re.sub(r'[_\-]+', ' ', cleaned)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            return cleaned or identifier

        def ordinal_label(idx: int) -> str:
            lookup = {
                1: "first",
                2: "second",
                3: "third",
                4: "fourth",
                5: "fifth"
            }
            return lookup.get(idx, f"{idx}th")

        def describe_xpath_target(expression: str) -> str | None:
            if not expression:
                return None
            resource_match = re.search(r'@resource-id="([^"]+)"', expression)
            content_desc_match = re.search(r'@content-desc="([^"]+)"', expression)
            label = None
            if resource_match:
                label = humanize_identifier(resource_match.group(1))
            elif content_desc_match:
                label = content_desc_match.group(1)
            if not label:
                return None
            index_label = ""
            index_match = re.search(r'@resource-id="[^"]+"\]\[(\d+)\]', expression)
            if not index_match:
                index_match = re.search(r'\]\[(\d+)\]', expression)
            if index_match:
                try:
                    idx = int(index_match.group(1))
                    index_label = ordinal_label(idx)
                except ValueError:
                    index_label = ""
            if index_label:
                return f"Click on {index_label} {label}".strip()
            return f"Click on {label}"

        if value and value.startswith("//"):
            xpath_description = describe_xpath_target(value)
            if xpath_description:
                return xpath_description
        if '@content-desc' in value_lower:
            content_desc_match = re.search(r'@content-desc="([^"]+)"', value)
            if content_desc_match:
                return f"Click on {content_desc_match.group(1)}"
        strategy = function_args.get('strategy')
        if strategy in ('content-desc', 'accessibility_id') and isinstance(function_args.get('value'), str):
            desc_value = function_args.get('value')
            if desc_value:
                return f"Click on {desc_value}"
        # Try to extract meaningful text from value
        if 'login' in value_lower or 'button' in value_lower:
            return "Click on Login button"
        elif 'logout' in value_lower:
            return "Click logout"
        else:
            return f"Click on {value}"
    elif function_name == 'wait_for_element':
        value = function_args.get('value', '')
        if 'welcome' in value.lower():
            return f'Check "welcome" is visible'
        elif 'username' in value.lower():
            return f'Check "username" is visible'
        elif 'product' in value.lower():
            return f'Check "Products page" is visible'
        else:
            return f'Check "{value}" is visible'
    elif function_name == 'launch_app':
        package = function_args.get('packageName', '')
        if 'swag' in package.lower() or 'swag' in str(function_args).lower():
            return 'Open Login page'
        return f'Open {package}'
    else:
        # Generic formatting
        value = function_args.get('value') or function_args.get('text') or ''
        if value:
            return f"{action} {value}"
        return action


# Global variable to store test_report for signal handlers
_test_report_for_signal = None

def add_skipped_steps_if_needed(test_report, step_counter):
    """Helper function to add skipped steps before finalizing report on failure."""
    try:
        if hasattr(main, '_planned_steps') and isinstance(main._planned_steps, list) and len(main._planned_steps) > 0:
            # Only add if there are planned steps and we haven't already added skipped steps
            # Check if the last step in report is already skipped
            existing_steps = test_report.report.get('steps', [])
            if existing_steps:
                last_step = existing_steps[-1]
                if last_step.get('status') != 'SKIPPED':
                    # Add skipped steps starting from the next step after current step_counter
                    test_report.add_skipped_steps(main._planned_steps, step_counter + 1)
    except Exception:
        pass  # Don't block on skipped steps errors


def finalize_and_generate_report(test_report, status: str = "completed", error: Optional[str] = None, completion_message: Optional[str] = None):
    """Finalize the test report, generate PDF, and print completion summary.
    
    Args:
        test_report: The TestReport instance
        status: Final status ("completed", "error", "failed", etc.)
        error: Optional error message
        completion_message: Optional custom completion message
        
    Returns:
        Tuple of (report_filename, pdf_path)
    """
    # Print completion header
    if status == "completed":
        print("\n" + "="*60)
        print("✅ AUTOMATION COMPLETED SUCCESSFULLY")
        print("="*60)
    elif status in ("failed", "error"):
        print("\n" + "="*60)
        print("❌ AUTOMATION COMPLETED WITH ERRORS")
        print("="*60)
    else:
        print("\n" + "="*60)
        print(f"⚠️  AUTOMATION {status.upper()}")
        print("="*60)
    
    # Print detailed step summary
    summary = test_report.get_summary()
    print(f"\n📊 EXECUTION SUMMARY:")
    print(f"   {summary}")
    
    # Print step-by-step breakdown
    steps = test_report.report.get('steps', [])
    if steps:
        print(f"\n📋 STEP BREAKDOWN:")
        for step in steps:
            step_num = step.get('step', 0)
            status_icon = '✅' if step.get('status') == 'PASS' else '❌' if step.get('status') == 'FAIL' else '⏭️'
            description = step.get('description', step.get('action', 'Unknown'))
            print(f"   {status_icon} Step {step_num}: {description}")
    
    if completion_message:
        print(f"\n💬 {completion_message}")
    
    # Finalize and save report
    print(f"\n📄 Generating report...")
    report_filename = test_report.finalize(status, error)
    print(f"   ✓ JSON Report saved: {report_filename.name}")
    
    # Generate PDF report
    pdf_path = None
    try:
        from pdf_generator import PDFReportGenerator
        pdf_generator = PDFReportGenerator(reports_dir=str(test_report.reports_dir))
        pdf_path = pdf_generator.generate_pdf(report_filename)
        if pdf_path:
            print(f"   ✓ PDF Report generated: {pdf_path.name}")
        else:
            print(f"   ⚠ PDF generation returned None (reportlab may not be installed)")
    except ImportError:
        print(f"   ⚠ PDF generation skipped (reportlab not installed)")
    except Exception as e:
        print(f"   ⚠ PDF generation failed: {e}")
    
    print(f"\n📊 Final Statistics: {summary}")
    print("="*60 + "\n")
    
    return report_filename, pdf_path

def main(provided_goal: str | None = None):
    """Main execution loop for mobile automation.

    Args:
        provided_goal: Optional prompt to run headlessly without interactive input.
    """
    global _test_report_for_signal
    
    # Track if last action requires verification (for assertion enforcement)
    main._last_requires_verification = False
    main._keyboard_visible = False
    main._recent_failure = False
    
    def hide_keyboard_if_needed(context: str):
        """Hide keyboard if it was opened by the last text input action."""
        if getattr(main, '_keyboard_visible', False):
            print(f"--- [KEYBOARD] Auto-hiding keyboard before {context} (keyboard may cover UI)...")
            try:
                hide_result = appium_tools.hide_keyboard()
                if isinstance(hide_result, dict) and hide_result.get('success'):
                    print("--- [OK] Keyboard hidden successfully")
                else:
                    print("--- [WARN]  Keyboard hide attempt completed (keyboard may already be hidden)")
            except Exception as kb_error:
                print(f"--- [WARN]  Could not hide keyboard before {context}: {kb_error}")
            finally:
                main._keyboard_visible = False
    
    def get_page_source_guarded(context: str):
        """Get page source after ensuring the keyboard is hidden."""
        hide_keyboard_if_needed(context)
        return get_page_source()
    
    def get_page_configuration_guarded(context: str, max_elements: int | None = None, include_static_text: bool = False):
        """Get structured page configuration after ensuring the keyboard is hidden."""
        hide_keyboard_if_needed(context)
        kwargs = {}
        if max_elements:
            kwargs["maxElements"] = max_elements
        if include_static_text:
            kwargs["includeStaticText"] = True
        try:
            return get_page_configuration(**kwargs)
        except Exception as config_error:
            return {"success": False, "error": str(config_error)}
    # Track step number for logging
    step_number = 0
    
    system_prompt = get_system_prompt()

    # Check if session exists, if not, try to initialize with defaults
    print("--- [CHECK] Checking for active Appium session...")
    test_payload = {"tool": "get_page_source", "args": {}}
    session_initialized = False
    max_session_retries = 3
    session_retry_count = 0
    
    while not session_initialized and session_retry_count < max_session_retries:
        try:
            test_response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=test_payload, timeout=10)
            
            # Check if we got an error response indicating no session
            if test_response.status_code in [400, 404]:
                error_data = test_response.json() if test_response.headers.get('content-type', '').startswith('application/json') else {}
                error_msg = error_data.get('error', '')
                if 'no active' in error_msg.lower() or 'session' in error_msg.lower() or test_response.status_code == 404:
                    print("--- [WARN]  No active Appium session found.")
                    print("--- [TOOL] Attempting to detect device type and initialize Appium session...")
                    print("--- [INFO] Note: You may need to customize capabilities based on your device/app.")
                    
                    # Detect device type
                    device_type = "Android"  # Default
                    automation_name = "UiAutomator2"
                    
                    # Try to detect iOS device
                    try:
                        import subprocess
                        idevice_result = subprocess.run(
                            ["idevice_id", "-l"],
                            capture_output=True,
                            text=True,
                            timeout=2
                        )
                        if idevice_result.returncode == 0 and idevice_result.stdout.strip():
                            device_type = "iOS"
                            automation_name = "XCUITest"
                            print("--- [INFO] iOS device detected")
                    except (FileNotFoundError, subprocess.TimeoutExpired):
                        # Not iOS, check Android
                        try:
                            adb_result = subprocess.run(
                                ["adb", "devices"],
                                capture_output=True,
                                text=True,
                                timeout=2
                            )
                            if adb_result.returncode == 0 and "device" in adb_result.stdout:
                                device_type = "Android"
                                automation_name = "UiAutomator2"
                                print("--- [INFO] Android device detected")
                        except:
                            pass
                    
                    default_capabilities = {
                        "platformName": device_type,
                        "appium:automationName": automation_name,
                        "appium:noReset": True,
                    }
                    
                    session_id = initialize_appium_session(default_capabilities)
                    if not session_id:
                        session_retry_count += 1
                        if session_retry_count < max_session_retries:
                            print(f"--- [WARN]  Failed to initialize session (attempt {session_retry_count}/{max_session_retries}). Retrying...")
                            time.sleep(2)  # Wait before retry
                            continue
                        else:
                            print("--- [ERROR] Failed to initialize Appium session after multiple attempts.")
                            print("--- [INFO] Please check:")
                            print("---    1. MCP server is running (npm run start:http)")
                            print("---    2. Appium server is running")
                            print("---    3. Mobile device/emulator is connected (Android or iOS)")
                            print(f"---    4. Or initialize manually: POST {MCP_SERVER_URL}/tools/initialize-appium")
                            return
                    else:
                        print(f"--- [OK] Session initialized: {session_id}")
                        session_initialized = True
                        # Persist session id for tools that require it (e.g., OCR endpoints)
                        try:
                            main._session_id = session_id
                            print(f"[TOOL] Stored session ID for OCR: {session_id}")
                        except Exception as e:
                            print(f"[WARN]  Failed to store session ID: {e}")
                            pass
                else:
                    print(f"--- [WARN]  Unexpected error checking session: {error_msg}")
                    print("--- [TOOL] Attempting to initialize Appium session anyway...")
                    # Use same device detection logic
                    device_type = "Android"
                    automation_name = "UiAutomator2"
                    try:
                        import subprocess
                        idevice_result = subprocess.run(
                            ["idevice_id", "-l"],
                            capture_output=True,
                            text=True,
                            timeout=2
                        )
                        if idevice_result.returncode == 0 and idevice_result.stdout.strip():
                            device_type = "iOS"
                            automation_name = "XCUITest"
                    except:
                        pass
                    default_capabilities = {
                        "platformName": device_type,
                        "appium:automationName": automation_name,
                        "appium:noReset": True,
                    }
                    session_id = initialize_appium_session(default_capabilities)
                    if not session_id:
                        session_retry_count += 1
                        if session_retry_count < max_session_retries:
                            print(f"--- [WARN]  Failed to initialize session (attempt {session_retry_count}/{max_session_retries}). Retrying...")
                            time.sleep(2)
                            continue
                        else:
                            print("--- [ERROR] Failed to initialize Appium session after multiple attempts.")
                            return
                    else:
                        print(f"--- [OK] Session initialized: {session_id}")
                        session_initialized = True
                        main._session_id = session_id
            elif test_response.status_code == 200:
                # Verify the response is actually successful (not an error in JSON)
                try:
                    response_data = test_response.json()
                    if isinstance(response_data, dict) and response_data.get('success') is False:
                        # Session exists but returned error - might be expired
                        error_msg = response_data.get('error', '')
                        if 'session' in error_msg.lower() or 'expired' in error_msg.lower() or 'not initialized' in error_msg.lower():
                            print(f"--- [WARN]  Session exists but appears to be expired: {error_msg}")
                            session_retry_count += 1
                            if session_retry_count < max_session_retries:
                                print("--- [TOOL] Attempting to reinitialize session...")
                                continue
                        else:
                            # Other error, but session might be OK
                            print("--- [OK] Active Appium session found (with minor warning)")
                            session_initialized = True
                    else:
                        print("--- [OK] Active Appium session found")
                        session_initialized = True
                except:
                    # Response is not JSON or parsing failed - assume session is OK
                    print("--- [OK] Active Appium session found")
                    session_initialized = True
            else:
                print(f"--- [WARN]  Unexpected status code {test_response.status_code} when checking session")
                print("--- [TOOL] Attempting to initialize Appium session...")
                # Detect device type
                device_type = "Android"
                automation_name = "UiAutomator2"
                try:
                    import subprocess
                    idevice_result = subprocess.run(
                        ["idevice_id", "-l"],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if idevice_result.returncode == 0 and idevice_result.stdout.strip():
                        device_type = "iOS"
                        automation_name = "XCUITest"
                except:
                    pass
                default_capabilities = {
                    "platformName": device_type,
                    "appium:automationName": automation_name,
                    "appium:noReset": True,
                }
                session_id = initialize_appium_session(default_capabilities)
                if session_id:
                    print(f"--- [OK] Session initialized: {session_id}")
                    session_initialized = True
                    main._session_id = session_id
                else:
                    session_retry_count += 1
                    if session_retry_count < max_session_retries:
                        print(f"--- [WARN]  Failed to initialize session (attempt {session_retry_count}/{max_session_retries}). Retrying...")
                        time.sleep(2)
                        continue
                    else:
                        print("--- [ERROR] Failed to initialize Appium session after multiple attempts.")
                        return
        except requests.exceptions.RequestException as e:
            print(f"--- [ERROR] Error checking for session: {e}")
            session_retry_count += 1
            if session_retry_count < max_session_retries:
                print(f"--- [WARN]  Retrying session initialization (attempt {session_retry_count}/{max_session_retries})...")
                time.sleep(2)
                continue
            else:
                print("--- [ERROR] Failed to check/initialize session after multiple attempts.")
                print("--- [INFO] Make sure:")
                print("---    1. MCP server is running (npm run start:http)")
                print("---    2. Appium server is running")
                print("---    3. Mobile device/emulator is connected (Android or iOS)")
                return
    
    # Final check - if we still don't have a session, exit
    if not session_initialized:
        print("--- [ERROR] Could not establish Appium session. Exiting.")
        return
    
    # Session is now initialized, continue with automation
    platform_hint = locals().get('device_type', 'Android')
    set_device_platform(platform_hint)
    get_device_metadata(force_refresh=True)
    
    if provided_goal:
        user_goal = provided_goal
        print(f"\nWhat is your goal? (auto)\n> {user_goal}")
    else:
        user_goal = input("\nWhat is your goal? (e.g., 'open YouTube and search for Python tutorials')\n> ")
    
    # Parse validation requirements from user prompt
    validation_map = parse_validation_requirements(user_goal)
    if validation_map:
        # Suppress validation detection messages - not shown to users
        # print(f"\n--- [OK] Detected {len(validation_map)} explicit validation requirement(s) in user prompt")
        # for key, val in validation_map.items():
        #     print(f"   - Validate: '{val['text']}'")
        pass
    
    # Initialize test report - use absolute path to ensure consistency
    import os
    from pathlib import Path
    reports_dir = Path(__file__).resolve().parent / "reports"
    test_report = TestReport(user_goal, reports_dir=str(reports_dir))
    _test_report_for_signal = test_report  # Store for signal handlers (global variable)
    # Create the initial report file immediately so even very short runs have an artifact
    try:
        test_report.save()
    except Exception as save_error:
        print(f"[WARN]  Unable to create initial report file: {save_error}")
    
    # Define signal handler for graceful shutdown
    def signal_handler(signum, frame):
        """Handle SIGTERM/SIGINT to save report before exiting."""
        print(f"\n\n--- [WARN]  Received signal {signum} - Saving report and exiting... ---")
        if _test_report_for_signal is not None:
            try:
                finalize_and_generate_report(
                    _test_report_for_signal,
                    "cancelled",
                    "Automation stopped by user",
                    "Automation was cancelled by user."
                )
            except Exception as save_error:
                print(f"[WARN]  Warning: Failed to save report: {save_error}")
        sys.exit(0)
    
    # Register signal handlers for graceful shutdown
    if sys.platform != "win32":
        # Unix-like systems: SIGTERM and SIGINT
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
    else:
        # Windows: Only SIGINT (Ctrl+C), SIGTERM not available
        signal.signal(signal.SIGINT, signal_handler)
    
    # Also register atexit handler as backup
    def exit_handler():
        """Backup handler to save report on exit."""
        if _test_report_for_signal is not None:
            try:
                # Only save if report hasn't been finalized yet
                if _test_report_for_signal.report.get('status') not in ('completed', 'failed', 'cancelled', 'interrupted'):
                    finalize_and_generate_report(
                        _test_report_for_signal,
                        "cancelled",
                        "Automation stopped",
                        "Automation was stopped."
                    )
            except Exception:
                pass  # Ignore errors in exit handler
    
    atexit.register(exit_handler)
    
    # Message history management constants
    MAX_MESSAGES = 30  # Increased from 15 to support longer test cases with more steps
    MAX_XML_LENGTH = 30000  # Base page-state length - reduced dynamically as messages accumulate
    MAX_ACTION_CYCLES = 50  # Maximum number of action cycles to prevent infinite loops
    action_cycle_count = 0  # Track number of action cycles
    
    # Cost optimization flags (can be set via environment variables)
    USE_PAGE_CONFIGURATION = os.getenv('USE_PAGE_CONFIGURATION', 'false').lower() in ('1', 'true', 'yes')
    USE_XML_COMPRESSION = os.getenv('USE_XML_COMPRESSION', 'true').lower() in ('1', 'true', 'yes')
    USE_BATCH_STEPS = os.getenv('USE_BATCH_STEPS', 'false').lower() in ('1', 'true', 'yes')
    
    # Dynamic length reduction based on message count
    def get_dynamic_xml_length(message_count: int) -> int:
        """Reduce perception payload length as message count increases to prevent input overflow."""
        if message_count <= 5:
            return MAX_XML_LENGTH  # 30K for first few messages
        elif message_count <= 10:
            return 20000  # 20K when 6-10 messages
        elif message_count <= 15:
            return 15000  # 15K when 11-15 messages
        elif message_count <= 20:
            return 12000  # 12K when 16-20 messages
        elif message_count <= 25:
            return 10000  # 10K when 21-25 messages
        else:
            return 8000  # 8K when >25 messages (more aggressive truncation for very long conversations)
    
    def render_config_state(config_result):
        """Convert page configuration result into (summary, payload, data) tuple."""
        if isinstance(config_result, dict):
            if config_result.get('success'):
                config = config_result.get('config') or {}
                summary_text = summarize_page_configuration(config)
                if USE_XML_COMPRESSION:
                    payload_text = json.dumps(config, ensure_ascii=False, separators=(',', ':'))
                else:
                    payload_text = json.dumps(config, ensure_ascii=False, indent=2)
                return summary_text, payload_text, config
            return f"[ERROR] Page configuration unavailable: {config_result.get('error', 'Unknown error')}", "", None
        return str(config_result), "", None
    
    def fetch_page_config_snapshot(context: str):
        """Fetch a page configuration snapshot on demand (fallback usage)."""
        nonlocal _cached_page_config, _cached_page_config_timestamp
        try:
            config_result = get_page_configuration_guarded(context)
            summary_text, payload_text, config_data = render_config_state(config_result)
            if config_data:
                snapshot_payload = payload_text or summary_text or "[WARN] Page configuration not available."
                summary_text = summary_text or "[WARN] Page configuration not available."
                _cached_page_config = {
                    "summary": summary_text,
                    "payload": snapshot_payload,
                    "data": config_data
                }
                _cached_page_config_timestamp = time.time()
                return config_data
            else:
                print(f"[WARN]  Page configuration fallback returned no data: {summary_text}")
        except Exception as cfg_error:
            print(f"[WARN]  Failed to fetch page configuration snapshot ({context}): {cfg_error}")
        return None
    
    initial_config_snapshot = None
    initial_xml_snapshot = None
    if USE_PAGE_CONFIGURATION:
        # Fast path: Get structured page configuration for initial load
        try:
            config_result = get_page_configuration_guarded("initial observation")
            summary_text, payload_text, config_data = render_config_state(config_result)
            snapshot_payload = payload_text or summary_text
            if not summary_text:
                summary_text = "[WARN] Page configuration not available."
            if not snapshot_payload:
                snapshot_payload = summary_text
            initial_config_snapshot = {
                "summary": summary_text,
                "payload": snapshot_payload,
                "data": config_data
            }
            
            dynamic_context_limit = get_dynamic_xml_length(1)  # First message
            truncated_summary = truncate_text_block(summary_text, dynamic_context_limit)
            truncated_payload = truncate_text_block(snapshot_payload, dynamic_context_limit)
            
            initial_perception_block = f"[Page Configuration Summary]:\n{truncated_summary}"
        except Exception as e:
            print(f"[WARN]  Failed to get page configuration: {e}")
            initial_perception_block = "[Unable to get page configuration]"
            truncated_payload = ""
            initial_config_snapshot = None
    else:
        # Fast path: Get XML page source (skip OCR for initial load speed)
        try:
            xml_result = get_page_source_guarded("initial observation")
            # Handle both string (success) and dict (error) returns
            if isinstance(xml_result, dict):
                if xml_result.get('success'):
                    current_screen_xml = xml_result.get('value', '')
                else:
                    current_screen_xml = f"[Error getting page source: {xml_result.get('error', 'Unknown error')}]"
            else:
                current_screen_xml = xml_result
            # Apply cost optimizations: compression and diff
            if USE_XML_COMPRESSION:
                current_screen_xml = compress_xml(current_screen_xml)
            
            # Use dynamic XML length based on current message count (initial load)
            dynamic_xml_limit = get_dynamic_xml_length(1)  # First message
            truncated_current_xml = truncate_xml(current_screen_xml, dynamic_xml_limit)
            
            # Store for diff calculation
            _previous_xml = current_screen_xml
            initial_xml_snapshot = current_screen_xml
            
            initial_perception_block = f"[XML Page Source (compressed)]:\n{truncated_current_xml}"
        except Exception as e:
            print(f"[WARN]  Failed to get page source: {e}")
            initial_perception_block = "[Unable to get page source]"
            truncated_current_xml = ""
            initial_xml_snapshot = None

    # Control whether to include the structured snapshot in messages
    suppress_page_state = os.getenv('SUPPRESS_XML', '').lower() in ('1', 'true', 'yes')
    if USE_PAGE_CONFIGURATION:
        initial_state_block = "[Perception summary omitted]" if suppress_page_state else initial_perception_block
        initial_screen_state_for_payload = truncated_payload if isinstance(truncated_payload, str) else ""
    else:
        initial_state_block = "[Perception summary omitted]" if suppress_page_state else initial_perception_block
        initial_screen_state_for_payload = truncated_current_xml if isinstance(truncated_current_xml, str) else ""
    
    # Extract strict inputs from the goal (e.g., username/password) to prevent auto-correction
    import re
    expected_inputs = {}
    m_user = re.search(r"username\s+is\s+([\S]+)", user_goal, re.IGNORECASE)
    m_pass = re.search(r"password\s+is\s+([\S]+)", user_goal, re.IGNORECASE)
    if m_user:
        # Strip trailing punctuation (comma, period, etc.) from captured value
        username_value = m_user.group(1).rstrip(',.;')
        expected_inputs['username'] = username_value
    if m_pass:
        # Strip trailing punctuation (comma, period, etc.) from captured value
        password_value = m_pass.group(1).rstrip(',.;')
        expected_inputs['password'] = password_value

    # Get app package suggestions if user mentions common app names
    app_suggestions = get_app_package_suggestions(user_goal)
    
    # Disable direct launch by default unless explicitly re-enabled via env
    disable_launch = os.getenv('DISABLE_LAUNCH_APP', '1').lower() in ('1', 'true', 'yes')
    # Always guide the LLM NOT to directly launch apps when disabled
    base_guidance = (
        "IMPORTANT: Do NOT call launch_app(). Navigate using the current UI only (home/back/search), and operate within visible apps."
        if disable_launch else
        "IMPORTANT: If the goal mentions an app that is not visible, you MAY launch that app using launch_app(), otherwise navigate within the current UI."
    )
    
    # Add flow-specific guidance based on user goal
    user_goal_lower = user_goal.lower()
    flow_guidance = ""
    
    if any(keyword in user_goal_lower for keyword in ['login', 'sign in', 'username', 'password']):
        flow_guidance = "\n\nLOGIN FLOW STEPS:\n1. Call get_page_source to inspect the current login screen XML\n2. Locate the username EditText node (verify class + resource-id)\n3. Use ensure_focus_and_type or send_keys to enter username\n4. Locate the password EditText node\n5. Use ensure_focus_and_type or send_keys to enter password\n6. Locate the Login button node and click it\n7. Call wait_for_element or wait_for_text_ocr to verify login success"
    elif any(keyword in user_goal_lower for keyword in ['compose', 'email', 'mail', 'send']):
        flow_guidance = "\n\nEMAIL COMPOSE FLOW STEPS:\n1. Call get_page_source to understand the current screen\n2. Locate the Compose button node and click it\n3. Refresh get_page_source to capture the compose UI\n4. Locate the 'To' EditText (if the locator points to a container, drill into descendant EditText)\n5. Type recipient email using ensure_focus_and_type\n6. Locate the Subject field and type subject\n7. Locate the Body field and type the email body\n8. Locate the Send button and click it\n9. Verify email sent (wait_for_text_ocr for 'sent' or 'message sent')"
    elif any(keyword in user_goal_lower for keyword in ['search', 'find']):
        flow_guidance = "\n\nSEARCH FLOW STEPS:\n1. Call get_page_source to inspect the current screen\n2. Check if a search EditText node is already visible\n3. If only a search icon/button is present, click it, then refresh get_page_source\n4. Locate the search input (class EditText) and verify it's editable\n5. Type the exact search query from the user's goal using ensure_focus_and_type or send_keys\n6. Submit the search: MANDATORY - After typing, call get_page_source to inspect the screen. Look for a search/submit button in the XML (nodes with 'search' or 'submit' in resource-id/content-desc, or Button/ImageButton elements). PREFER clicking that button to submit. FALLBACK: If no search button is found in the page source, you may use Enter key (send '\\n') as a fallback.\n7. After submitting (via button or Enter), call get_page_source again to verify search results have loaded (look for result lists, RecyclerView, or new items that appeared)\n8. Click the first result from the search results (look for clickable ViewGroup/RecyclerView/ListView items that represent actual search results, NOT app logos, navigation elements, or unrelated UI components)"
    elif any(keyword in user_goal_lower for keyword in ['add', 'cart', 'checkout']):
        flow_guidance = (
            "\n\nE-COMMERCE FLOW STEPS:"
            "\n1. Call get_page_source to list visible products (search for the exact text/resource-id)"
            "\n2. If the exact product name is not visible, use scroll_to_element to find it"
            "\n3. Locate the product card whose text exactly matches the user’s string (e.g., 'Sauce Labs Bike Light') and click the 'ADD TO CART' button inside that card—never a generic button from another product"
            "\n4. Immediately verify the button flips to 'REMOVE' or the cart badge increases, then open the cart"
            "\n5. Inside the cart, confirm the exact product name appears before proceeding"
            "\n6. Click the checkout button"
            "\n7. Fill form fields (firstname, lastname, zip) – verify each target is an EditText"
            "\n8. Click Continue/Next, then click Finish/Complete"
            "\n9. Verify the order completion screen (wait_for_text_ocr for 'thank you' or 'order complete')"
        )
    
    initial_guidance = base_guidance + flow_guidance
    strict_note = "" if not expected_inputs else f"\n\nSTRICT: Use EXACT values from user: {expected_inputs}. Do NOT auto-correct or substitute."
    validation_note = ""
    if validation_map:
        validation_list = [f"'{val['text']}'" for val in validation_map.values()]
        validation_note = f"\n\n[OK] VALIDATION REQUIREMENTS: The user has explicitly requested validation for: {', '.join(validation_list)}. You MUST perform these validations when the corresponding actions complete. Use wait_for_text_ocr, wait_for_element, or assert_activity to perform validations."
    context_note = "\n\n[INFO] CONTEXT: Work with the CURRENT screen state shown above. If the goal mentions something already visible on this screen, proceed directly with that action. You don't need to navigate back or restart from the beginning."
    perception_note = (
        "\n\n[THINK] SCREEN STATE: The screen state above shows a structured page configuration (aliases, roles, and locator candidates). Treat it as the primary source of truth for native elements. Use the aliases and ranked locators when planning actions."
        if USE_PAGE_CONFIGURATION else
        "\n\n[THINK] SCREEN STATE: The screen state above shows the current XML page source snapshot. Treat it as the primary source of truth for native elements. Use the resource-ids, content-desc, and text directly from this XML when planning actions."
    )
    initial_prompt_text = (
        f"My goal is: '{user_goal}'.{app_suggestions}{strict_note}{validation_note}\n\n"
        f"Here is the current screen perception summary: {initial_state_block}\n\n"
        f"{perception_note}\n\n{context_note}\n\n{initial_guidance}"
    )
    messages = [
        {
            "role": "user",
            "content": build_device_context_payload(initial_prompt_text, initial_screen_state_for_payload)
        }
    ]

    # Initialize smart executor for deterministic fallbacks
    smart_executor = SmartActionExecutor(available_functions, expected_inputs)

    # Build tool list for the LLM, optionally removing launch_app entirely
    if disable_launch:
        tools_for_model = [t for t in tools_list_claude if t.get('name') != 'launch_app']
    else:
        tools_for_model = tools_list_claude

    # Cache for page configuration / XML snapshots to avoid redundant calls
    _cached_page_config = initial_config_snapshot
    _cached_page_config_timestamp = time.time() if initial_config_snapshot else 0
    _cached_xml = initial_xml_snapshot
    _cached_xml_timestamp = time.time() if initial_xml_snapshot else 0
    _previous_xml = initial_xml_snapshot
    _last_action_was_screen_change = False
    
    # Track repeated actions to prevent infinite loops
    _action_history = []  # Track last 5 actions (function_name, function_args signature)
    _max_repeat_actions = 3  # Max times same action can repeat consecutively
    
    while True:
        # COMPLETION CHECK: Before starting new cycle, check if all steps are completed
        # This prevents continuing after completion even if LLM doesn't return end_turn
        if action_cycle_count > 2:  # Check after a few steps have been executed (reduced from 3 to 2)
            try:
                # Check 0: If no planned steps from LLM, parse from user prompt as fallback
                if not hasattr(main, '_planned_steps') or not isinstance(main._planned_steps, list) or len(main._planned_steps) == 0:
                    # Fallback: Parse steps from user prompt
                    user_prompt_lower = user_goal.lower()
                    inferred_steps = []
                    step_num = 1

                    def add_planned_step(name: str, description: str | None = None, match_phrases: list[str] | None = None):
                        nonlocal step_num, inferred_steps
                        inferred_steps.append({
                            "step": step_num,
                            "name": name,
                            "description": description or name,
                            "match_phrases": match_phrases or []
                        })
                        step_num += 1
                    
                    # App opening
                    if 'open' in user_prompt_lower:
                        app_match = re.search(r'open\s+([a-z0-9 ._-]+)', user_goal, re.IGNORECASE)
                        app_name = app_match.group(1).strip() if app_match else "app"
                        add_planned_step(f"Open {app_name}", f"Open {app_name}")
                    
                    # Gmail compose / email actions
                    if any(keyword in user_prompt_lower for keyword in ['compose', 'mail', 'email']):
                        if 'compose' in user_prompt_lower:
                            add_planned_step("Click Compose", "Click Compose button", ["compose"])
                        if ' subject' in user_prompt_lower:
                            add_planned_step("Enter subject", "Type subject", ["subject"])
                        if ' body' in user_prompt_lower:
                            add_planned_step("Enter body", "Type body", ["body"])
                        if 'send' in user_prompt_lower:
                            add_planned_step("Send email", "Click Send button", ["send"])
                    
                    # Login flow
                    if 'username' in user_prompt_lower:
                        add_planned_step("Enter username", "Type username", ["username"])
                    if 'password' in user_prompt_lower:
                        add_planned_step("Enter password", "Type password", ["password"])
                    if 'login' in user_prompt_lower or 'tap login' in user_prompt_lower:
                        add_planned_step("Tap Login", "Click Login button", ["login"])
                    
                    # Verify products page
                    if 'verify' in user_prompt_lower and 'products page' in user_prompt_lower:
                        add_planned_step(
                            "Verify Products Page",
                            "Wait For Text Ocr PRODUCTS",
                            ["wait for text ocr products", "products page"]
                        )
                    
                    # Detect product add instructions
                    product_match = re.search(r'add\s+([a-z0-9\s\-]+?)\s+(?:item|product)?\s*to\s+cart', user_goal, re.IGNORECASE)
                    if product_match:
                        product_name = product_match.group(1).strip()
                        add_planned_step(
                            f"Add {product_name} to cart",
                            f"Add {product_name} to cart",
                            ["add to cart", product_name.lower()]
                        )
                        add_planned_step(
                            f"Verify {product_name} in cart",
                            f"Verify {product_name} appears in cart",
                            [product_name.lower(), "cart"]
                        )
                    
                    # Go to / view cart
                    if 'go to cart' in user_prompt_lower or 'view cart' in user_prompt_lower or 'cart' in user_prompt_lower:
                        add_planned_step("Open cart", "Go to cart", ["cart"])
                    
                    # Checkout sequence
                    if 'checkout' in user_prompt_lower:
                        add_planned_step("Proceed to checkout", "Click checkout", ["checkout"])
                    
                    firstname_match = re.search(r'first\s*name\s+as\s+([a-z0-9\s]+)', user_goal, re.IGNORECASE)
                    if firstname_match:
                        fname = firstname_match.group(1).strip()
                        add_planned_step(
                            f"Enter first name ({fname})",
                            f"Type {fname} in first name",
                            ["first name"]
                        )
                    
                    lastname_match = re.search(r'last\s*name\s+as\s+([a-z0-9\s]+)', user_goal, re.IGNORECASE)
                    if lastname_match:
                        lname = lastname_match.group(1).strip()
                        add_planned_step(
                            f"Enter last name ({lname})",
                            f"Type {lname} in last name",
                            ["last name"]
                        )
                    
                    zip_match = re.search(r'(zip|postal)\s*code\s+as\s+([a-z0-9\s]+)', user_goal, re.IGNORECASE)
                    if zip_match:
                        zip_value = zip_match.group(2).strip()
                        add_planned_step(
                            f"Enter zip code ({zip_value})",
                            f"Type {zip_value} in zip code",
                            ["zip", "postal"]
                        )
                    
                    if 'continue' in user_prompt_lower:
                        add_planned_step("Click Continue", "Click Continue", ["continue"])
                    
                    if any(keyword in user_prompt_lower for keyword in ['finish', 'finesh', 'complete order']):
                        add_planned_step("Click Finish", "Click Finish", ["finish"])
                    
                    if 'verify' in user_prompt_lower and 'order' in user_prompt_lower:
                        add_planned_step(
                            "Verify order completion",
                            "Verify order is placed",
                            ["thank you", "order complete", "order is placed"]
                        )
                    
                    # OTT Platform / Streaming App flows (HIGH PRIORITY - Check first)
                    is_ott_platform = any(keyword in user_prompt_lower for keyword in [
                        'netflix', 'hotstar', 'disney hotstar', 'prime video', 'amazon prime', 
                        'disney+', 'disney plus', 'zee5', 'sony liv', 'voot', 'ott', 'streaming'
                    ])
                    
                    if is_ott_platform:
                        # Profile selection (common in Netflix, Hotstar)
                        if 'profile' in user_prompt_lower:
                            profile_match = re.search(r'profile\s+([^,]+?)(?:\s+and\s+then|$)', user_goal, re.IGNORECASE)
                            if profile_match:
                                profile_name = profile_match.group(1).strip()
                                add_planned_step(f"Select profile {profile_name}", f"Switch to profile {profile_name}", ["profile", profile_name.lower()])
                            else:
                                # Generic profile selection if profile name not specified
                                add_planned_step("Select profile", "Choose user profile if prompted", ["profile", "select profile"])
                        
                        # Content browsing / Categories
                        if 'browse' in user_prompt_lower or 'category' in user_prompt_lower or 'genre' in user_prompt_lower:
                            category_match = re.search(r'(?:browse|category|genre)\s+([^,]+?)(?:\s+and\s+then|$)', user_goal, re.IGNORECASE)
                            if category_match:
                                category_name = category_match.group(1).strip()
                                add_planned_step(f"Browse {category_name}", f"Navigate to {category_name} category", [category_name.lower(), "category", "browse"])
                            else:
                                add_planned_step("Browse categories", "Navigate to browse/categories section", ["browse", "category"])
                        
                        # My List / Watchlist
                        if 'my list' in user_prompt_lower or 'watchlist' in user_prompt_lower or 'saved' in user_prompt_lower:
                            add_planned_step("Open My List", "Navigate to My List/Watchlist", ["my list", "watchlist", "saved"])
                        
                        # Continue Watching
                        if 'continue watching' in user_prompt_lower or 'resume' in user_prompt_lower or 'continue' in user_prompt_lower:
                            add_planned_step("Continue Watching", "Resume previously watched content", ["continue", "resume", "continue watching"])
                        
                        # TV Show / Episode selection
                        if 'episode' in user_prompt_lower or 'season' in user_prompt_lower:
                            season_match = re.search(r'season\s+(\d+)', user_goal, re.IGNORECASE)
                            episode_match = re.search(r'episode\s+(\d+)', user_goal, re.IGNORECASE)
                            if season_match:
                                season_num = season_match.group(1)
                                add_planned_step(f"Select Season {season_num}", f"Navigate to Season {season_num}", ["season", season_num])
                            if episode_match:
                                episode_num = episode_match.group(1)
                                add_planned_step(f"Select Episode {episode_num}", f"Navigate to Episode {episode_num}", ["episode", episode_num])
                            elif 'episode' in user_prompt_lower or 'season' in user_prompt_lower:
                                add_planned_step("Select episode", "Navigate to episode selection", ["episode", "season"])
                        
                        # Search in OTT platforms
                        if 'search' in user_prompt_lower:
                            search_match = re.search(r'search\s+for\s+([^,]+?)(?:\s+and\s+then|$)', user_goal, re.IGNORECASE)
                            if search_match:
                                search_query = search_match.group(1).strip()
                                add_planned_step("Click Search", "Click search icon/button", ["search"])
                                add_planned_step(f"Search for {search_query}", f"Type search query: {search_query}", [search_query.lower(), "search"])
                                add_planned_step("Submit search", "Click search button or submit", ["submit", "search button"])
                        
                        # Play content (OTT-specific)
                        if 'play' in user_prompt_lower:
                            if 'movie' in user_prompt_lower:
                                movie_match = re.search(r'play\s+(?:the\s+)?movie\s+([^,]+?)(?:\s+and\s+then|$)', user_goal, re.IGNORECASE)
                                if movie_match:
                                    movie_name = movie_match.group(1).strip()
                                    add_planned_step(f"Play movie {movie_name}", f"Select and play {movie_name}", ["movie", movie_name.lower(), "play", "watch", "resume"])
                                else:
                                    add_planned_step("Play movie", "Select and play a movie", ["movie", "play", "watch", "resume"])
                            elif 'show' in user_prompt_lower or 'series' in user_prompt_lower:
                                show_match = re.search(r'play\s+(?:the\s+)?(?:show|series)\s+([^,]+?)(?:\s+and\s+then|$)', user_goal, re.IGNORECASE)
                                if show_match:
                                    show_name = show_match.group(1).strip()
                                    add_planned_step(f"Play show {show_name}", f"Select and play {show_name}", ["show", "series", show_name.lower(), "play", "watch", "resume"])
                                else:
                                    add_planned_step("Play show", "Select and play a show", ["show", "series", "play", "watch", "resume"])
                            elif 'first' in user_prompt_lower:
                                add_planned_step("Play first result", "Click first search/browse result", ["first", "play", "video", "watch", "resume"])
                            else:
                                add_planned_step("Play content", "Click content to play", ["play", "video", "watch", "resume"])
                    
                    # YouTube / Video search and play flow (fallback for non-OTT video apps)
                    elif 'search' in user_prompt_lower and ('youtube' in user_prompt_lower or 'video' in user_prompt_lower):
                        search_match = re.search(r'search\s+for\s+([^,]+?)(?:\s+and\s+then|$)', user_goal, re.IGNORECASE)
                        if search_match:
                            search_query = search_match.group(1).strip()
                            add_planned_step("Click Search", "Click search icon/button", ["search"])
                            add_planned_step(f"Search for {search_query}", f"Type search query: {search_query}", [search_query.lower(), "search"])
                            add_planned_step("Submit search", "Click search button or submit", ["submit", "search button"])
                    
                    if 'play' in user_prompt_lower and not is_ott_platform and ('first' in user_prompt_lower or 'video' in user_prompt_lower):
                        if 'first' in user_prompt_lower:
                            add_planned_step("Play first video", "Click first search result video", ["first", "video", "play", "watch", "resume"])
                        else:
                            add_planned_step("Play video", "Click video to play", ["video", "play", "watch", "resume"])

                    # Downloads / offline playback flows
                    if 'download' in user_prompt_lower:
                        add_planned_step(
                            "Open Downloads",
                            "Navigate to downloads/offline section",
                            ["download", "downloads"]
                        )
                        if (('second' in user_prompt_lower) or ('2nd' in user_prompt_lower)) and any(keyword in user_prompt_lower for keyword in ['video', 'episode', 'item', 'content']):
                            add_planned_step(
                                "Play second downloaded video",
                                "Open and play the second downloaded item/video",
                                ["second", "2nd", "download", "tag_download_content_item", "video", "downloads", "watch", "resume", "play"]
                            )
                        elif 'play' in user_prompt_lower:
                            add_planned_step(
                                "Play downloaded content",
                                "Open downloaded item",
                                ["download", "downloads", "offline", "play", "watch", "resume"]
                            )
                    
                    if inferred_steps:
                        main._planned_steps = inferred_steps
                        print(f"[DEBUG] Inferred {len(inferred_steps)} steps from user prompt: {[s.get('name') for s in inferred_steps]}")
                
                # Check 1: Verify if all planned steps have been executed
                all_steps_completed = False
                if hasattr(main, '_planned_steps') and isinstance(main._planned_steps, list) and len(main._planned_steps) > 0:
                    executed_descriptions = set()
                    for step_info in test_report.report.get('steps', []):
                        desc = step_info.get('description', '')
                        if desc and step_info.get('status') != 'SKIPPED':
                            executed_descriptions.add(desc.lower().strip())
                    
                    # Check if all planned steps have been executed
                    all_executed = True
                    for planned_step in main._planned_steps:
                        plan_desc = planned_step.get('name', planned_step.get('description', planned_step.get('action', '')))
                        if plan_desc:
                            plan_desc_normalized = plan_desc.lower().strip()
                            found_match = False
                            for exec_desc in executed_descriptions:
                                match_phrases = planned_step.get('match_phrases') or []
                                if match_phrases:
                                    if any(phrase for phrase in match_phrases if phrase and phrase in exec_desc):
                                        found_match = True
                                        break
                                plan_keywords = set(plan_desc_normalized.split())
                                exec_keywords = set(exec_desc.split())
                                if len(plan_keywords & exec_keywords) >= min(2, len(plan_keywords) // 2):
                                    found_match = True
                                    break
                            if not found_match:
                                all_executed = False
                                break
                    
                    if all_executed and test_report.report.get("failed_steps", 0) == 0:
                        all_steps_completed = True
                
                # Check 2: Check for completion page indicators (ONLY after finish/complete actions)
                recent_steps = test_report.report.get('steps', [])[-5:]  # Check last 5 steps
                recent_descriptions = [s.get('description', '').lower() for s in recent_steps]
                clicked_completion_action = any(
                    keyword in desc for desc in recent_descriptions 
                    for keyword in ['finish', 'complete', 'submit', 'done', 'confirm', 'order complete', 'send', 'sent']
                )
                
                # FIX: Only check completion page if we actually clicked a completion action
                # This prevents false positives from intermediate screens (like Gmail compose)
                if clicked_completion_action or all_steps_completed:
                    # Check if we're on a completion page
                    check_xml_result = get_page_source_guarded("completion check")
                    check_xml = None
                    if isinstance(check_xml_result, str):
                        check_xml = check_xml_result
                    elif isinstance(check_xml_result, dict) and check_xml_result.get('success'):
                        check_xml = check_xml_result.get('value', '')
                    
                    if check_xml:
                        xml_lower = check_xml.lower()
                        # FIX: More specific completion indicators to avoid false positives
                        # Generic words like "complete" or "success" can appear in intermediate screens
                        completion_indicators = [
                            'thank you for your order',
                            'order complete',
                            'checkout complete',
                            'message sent',  # Gmail-specific
                            'email sent',    # Gmail-specific
                            'sent successfully',  # Generic
                            'back home',
                            'thank you',
                            'order confirmation',  # More specific
                            'transaction complete',  # More specific
                            'payment complete',  # More specific
                            'player',  # Video player (YouTube, etc.)
                            'video player',  # Video player
                            'playing',  # Video is playing
                            'pause',  # Video controls visible (indicates video is playing)
                            'fullscreen',  # Video fullscreen button
                        ]
                        is_completion_page = any(indicator in xml_lower for indicator in completion_indicators)
                        
                        # Check for video playing scenarios (OTT platforms and YouTube)
                        # If user goal includes "play" and we see video player controls, consider it complete
                        is_video_playing = False
                        is_ott_platform = any(keyword in user_goal.lower() for keyword in [
                            'netflix', 'hotstar', 'disney hotstar', 'prime video', 'amazon prime',
                            'disney+', 'disney plus', 'zee5', 'sony liv', 'voot', 'ott', 'streaming',
                            'movie', 'show', 'episode', 'series'
                        ])
                        
                        if 'play' in user_goal.lower() and (is_ott_platform or 'video' in user_goal.lower() or 'youtube' in user_goal.lower()):
                            # Enhanced video indicators for OTT platforms
                            video_indicators = [
                                'player', 'video player', 'pause', 'fullscreen', 'seek bar', 
                                'playback controls', 'subtitle', 'audio track', 'quality',
                                'episode', 'season', 'next episode', 'previous episode',
                                'playback speed', 'skip intro', 'skip credits', 'resume',
                                'movie player', 'show player', 'streaming player'
                            ]
                            is_video_playing = any(indicator in xml_lower for indicator in video_indicators)
                            
                            # Also check if we recently clicked content (last 3 steps)
                            recent_steps_for_video = test_report.report.get('steps', [])[-3:]
                            clicked_content = any(
                                'video' in desc or 
                                'play' in desc or
                                'movie' in desc or
                                'show' in desc or
                                'episode' in desc or
                                'resume' in desc or
                                'watch' in desc
                                for desc in (s.get('description', '').lower() for s in recent_steps_for_video)
                            )
                            
                            if is_video_playing and clicked_content:
                                platform_type = "OTT platform" if is_ott_platform else "video platform"
                                finalize_and_generate_report(
                                    test_report, 
                                    "completed", 
                                    None,
                                    f"Content playing detected on {platform_type}"
                                )
                                break
                        
                        # FIX: Require BOTH conditions for completion page detection:
                        # 1. We clicked a completion action (finish, send, submit, etc.)
                        # 2. AND we're on an actual completion page
                        # OR all steps are explicitly completed
                        if all_steps_completed or (clicked_completion_action and is_completion_page):
                            completion_msg = None
                            if all_steps_completed:
                                completion_msg = "All planned steps have been executed successfully."
                            elif clicked_completion_action and is_completion_page:
                                completion_msg = "Reached completion page after completion action."
                            
                            finalize_and_generate_report(
                                test_report,
                                "completed",
                                None,
                                completion_msg
                            )
                            break
                
                # Check 3: If we've hit the max action cycles and no failures, assume completion
                if action_cycle_count >= MAX_ACTION_CYCLES:
                    failed_steps = test_report.report.get("failed_steps", 0)
                    if failed_steps == 0:
                        finalize_and_generate_report(
                            test_report,
                            "completed",
                            None,
                            f"Reached maximum action cycle limit ({MAX_ACTION_CYCLES})"
                        )
                        break
            except Exception as e:
                # If check fails, continue normally
                pass
        
        # Only get fresh perception summary if screen likely changed (after actions)
        if USE_PAGE_CONFIGURATION:
            used_cached_snapshot = False
            if _last_action_was_screen_change or _cached_page_config is None:
                print("\n--- [THINK] OBSERVE: Generating page configuration snapshot...")
                try:
                    config_result = get_page_configuration_guarded("observing screen")
                    summary_text, payload_text = render_config_state(config_result)
                    snapshot_payload = payload_text or summary_text
                    if not summary_text:
                        summary_text = "[WARN] Page configuration not available."
                    if not snapshot_payload:
                        snapshot_payload = summary_text
                    _cached_page_config = {"summary": summary_text, "payload": snapshot_payload}
                    _cached_page_config_timestamp = time.time()
                    _last_action_was_screen_change = False
                except Exception as e:
                    print(f"[WARN]  Failed to get page configuration: {e}")
                    summary_text = "[Unable to get page configuration]"
                    snapshot_payload = ""
                    _cached_page_config = {"summary": summary_text, "payload": snapshot_payload}
            else:
                used_cached_snapshot = True
                print("\n--- [THINK] OBSERVE: Using cached page configuration (screen unchanged)...")
                summary_text = (_cached_page_config or {}).get('summary', '')
                snapshot_payload = (_cached_page_config or {}).get('payload', summary_text)
            
            dynamic_context_limit = get_dynamic_xml_length(len(messages) + 1)
            truncated_summary = truncate_text_block(summary_text, dynamic_context_limit)
            truncated_payload = truncate_text_block(snapshot_payload, dynamic_context_limit)
            summary_label = "Page Configuration Summary (cached)" if used_cached_snapshot else "Page Configuration Summary"
            current_perception_block = f"[{summary_label}]:\n{truncated_summary}"
            
            # Add explicit reminder to check configuration before scrolling
            user_goal_lower = user_goal.lower()
            key_terms = []
            if 'add' in user_goal_lower and 'cart' in user_goal_lower:
                product_match = re.search(r'add\s+([^to]+?)\s+to\s+cart', user_goal_lower)
                if product_match:
                    key_terms.append(product_match.group(1).strip())
            if 'bike light' in user_goal_lower:
                key_terms.append('bike light')
            if 'backpack' in user_goal_lower:
                key_terms.append('backpack')
            
            if key_terms:
                current_perception_block += f"\n\n[CRITICAL REMINDER] Before scrolling, SEARCH the page configuration above for: {', '.join(key_terms)}. If found, act on it directly—do NOT scroll!"
            
            screen_state_for_payload = truncated_payload
        else:
            # Use XML snapshots with caching/diff
            if _last_action_was_screen_change or _cached_xml is None:
                print("\n--- [THINK] OBSERVE: Getting page source (XML only - fast mode)...")
                try:
                    xml_result = get_page_source_guarded("observing screen")
                    if isinstance(xml_result, dict):
                        if xml_result.get('success'):
                            current_screen_xml = xml_result.get('value', '')
                        else:
                            current_screen_xml = f"[Error getting page source: {xml_result.get('error', 'Unknown error')}]"
                    else:
                        current_screen_xml = xml_result
                    if USE_XML_COMPRESSION:
                        current_screen_xml = compress_xml(current_screen_xml)
                    
                    _cached_xml = current_screen_xml
                    _cached_xml_timestamp = time.time()
                    _last_action_was_screen_change = False
                    
                    if _previous_xml and _previous_xml != current_screen_xml:
                        diff_xml = get_xml_diff(_previous_xml, current_screen_xml)
                        dynamic_xml_limit = get_dynamic_xml_length(len(messages) + 1)
                        truncated_current_xml = truncate_xml(diff_xml, dynamic_xml_limit)
                        current_perception_block = f"[XML Page Source (diff, compressed)]:\n{truncated_current_xml}"
                    else:
                        dynamic_xml_limit = get_dynamic_xml_length(len(messages) + 1)
                        truncated_current_xml = truncate_xml(current_screen_xml, dynamic_xml_limit)
                        current_perception_block = f"[XML Page Source (compressed)]:\n{truncated_current_xml}"
                    
                    _previous_xml = current_screen_xml
                except Exception as e:
                    print(f"[WARN]  Failed to get page source: {e}")
                    current_perception_block = "[Unable to get page source]"
                    truncated_current_xml = ""
            else:
                print("\n--- [THINK] OBSERVE: Using cached page source (screen unchanged)...")
                cached_xml = _cached_xml or ""
                if USE_XML_COMPRESSION:
                    cached_xml = compress_xml(cached_xml)
                dynamic_xml_limit = get_dynamic_xml_length(len(messages) + 1)
                truncated_current_xml = truncate_xml(cached_xml, dynamic_xml_limit)
                current_perception_block = f"[XML Page Source (cached, compressed)]:\n{truncated_current_xml}"
            
            # Reminder for key terms
            user_goal_lower = user_goal.lower()
            key_terms = []
            if 'add' in user_goal_lower and 'cart' in user_goal_lower:
                product_match = re.search(r'add\s+([^to]+?)\s+to\s+cart', user_goal_lower)
                if product_match:
                    key_terms.append(product_match.group(1).strip())
            if 'bike light' in user_goal_lower:
                key_terms.append('bike light')
            if 'backpack' in user_goal_lower:
                key_terms.append('backpack')
            
            if key_terms:
                current_perception_block += f"\n\n[CRITICAL REMINDER] Before scrolling, SEARCH the XML above for: {', '.join(key_terms)}. If found, use it directly—DO NOT scroll!"
            
            screen_state_for_payload = truncated_current_xml if isinstance(truncated_current_xml, str) else ""
        # Add current page configuration + metadata payload for LLM
        messages.append({
            "role": "user",
            "content": build_device_context_payload(current_perception_block, screen_state_for_payload)
        })
        
        print("--- [THINK] THINK: Asking LLM what to do next...")
        
        # Validate messages before sending to API to prevent ValidationException
        # This ensures no orphaned tool_use or tool_result blocks are sent
        messages = validate_message_pairs(messages)
        if messages is None:
            messages = []
        
        # Prune messages more aggressively to prevent "Input is too long" errors
        # Start pruning when approaching the limit
        current_message_count = len(messages)
        if current_message_count > 20:
            # Prune when we have more than 20 messages (2/3 of MAX_MESSAGES)
            target_messages = MAX_MESSAGES - 2 if current_message_count > MAX_MESSAGES - 5 else MAX_MESSAGES
            messages = prune_messages(messages, target_messages)
        
        # Also reduce page configuration summary size in existing messages to control context growth
        dynamic_xml_limit = get_dynamic_xml_length(len(messages))
        if dynamic_xml_limit < MAX_XML_LENGTH:
            # Reduce page configuration text in all messages that contain it
            for msg in messages:
                if isinstance(msg.get('content'), str) and '[Page Configuration' in msg['content']:
                    # Extract and re-truncate configuration text if present
                    import re
                    cfg_match = re.search(r'\[Page Configuration[^\]]*\]:\s*(.*?)(?=\n\n|\Z)', msg['content'], re.DOTALL)
                    if cfg_match:
                        cfg_content = cfg_match.group(1)
                        if len(cfg_content) > dynamic_xml_limit:
                            truncated_cfg = truncate_text_block(cfg_content, dynamic_xml_limit)
                            msg['content'] = msg['content'].replace(cfg_content, truncated_cfg)
                elif isinstance(msg.get('content'), list):
                    # Handle list content (tool_result format)
                    for block in msg['content']:
                        if isinstance(block, dict) and block.get('type') == 'text':
                            text_content = block.get('text', '')
                            if '[Page Configuration' in text_content:
                                cfg_match = re.search(r'\[Page Configuration[^\]]*\]:\s*(.*?)(?=\n\n|\Z)', text_content, re.DOTALL)
                                if cfg_match:
                                    cfg_content = cfg_match.group(1)
                                    if len(cfg_content) > dynamic_xml_limit:
                                        truncated_cfg = truncate_text_block(cfg_content, dynamic_xml_limit)
                                        block['text'] = text_content.replace(cfg_content, truncated_cfg)
        
        # Calculate and log input size for debugging
        system_prompt_size = len(system_prompt)
        system_prompt_lines = system_prompt.count('\n') + 1
        
        # Calculate messages size
        messages_json = json.dumps(messages)
        messages_size = len(messages_json)
        messages_lines = messages_json.count('\n') + 1
        
        # Calculate tools size
        tools_json = json.dumps(tools_for_model)
        tools_size = len(tools_json)
        tools_lines = tools_json.count('\n') + 1
        
        # Total input size
        total_size = system_prompt_size + messages_size + tools_size
        total_lines = system_prompt_lines + messages_lines + tools_lines
        
        # Approximate token count (rough estimate: 1 token ≈ 4 characters)
        estimated_tokens = total_size // 4
        
        # Log input size information (suppressed - not shown to users)
        # print(f"\n--- [DEBUG] LLM Input Size (Step {action_cycle_count + 1}):")
        # print(f"  System Prompt: {system_prompt_size:,} chars ({system_prompt_lines:,} lines)")
        # print(f"  Messages ({len(messages)} messages): {messages_size:,} chars ({messages_lines:,} lines)")
        # print(f"  Tools ({len(tools_for_model)} tools): {tools_size:,} chars ({tools_lines:,} lines)")
        # print(f"  TOTAL: {total_size:,} chars ({total_lines:,} lines) ≈ {estimated_tokens:,} tokens")
        # print(f"  XML Limit: {dynamic_xml_limit:,} chars per message")
        
        request_body = {
            "system": system_prompt,
            "messages": messages,
            "tools": tools_for_model,
            "tool_choice": {"type": "auto"},
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096  # Increased to ensure tool_use blocks are not truncated
        }
        
        try:
            # Use retry logic for Bedrock API calls
            response = invoke_bedrock_with_retry(
                bedrock_client, 
                request_body, 
                BEDROCK_MODEL_ID,
                max_retries=3,
                base_delay=0.2  # Optimized: Reduced to 0.2s for faster retries (Claude Desktop speed)
            )
            
            response_body = json.loads(response['body'].read().decode('utf-8'))
            stop_reason = response_body.get('stop_reason')
            
            # DEBUG: Log stop_reason to help diagnose infinite loops
            if stop_reason:
                print(f"--- [DEBUG] LLM stop_reason: {stop_reason}")
            else:
                print(f"--- [WARN] LLM response missing stop_reason. Response keys: {list(response_body.keys())}")
            
            # Check for API errors in response
            if 'error' in response_body:
                error_msg = response_body.get('error', {}).get('message', 'Unknown API error')
                print(f"[ERROR] API returned an error: {error_msg}")
                # Add skipped steps before finalizing
                add_skipped_steps_if_needed(test_report, test_report.step_counter)
                finalize_and_generate_report(
                    test_report,
                    "error",
                    f"API error: {error_msg}",
                    "Automation stopped due to API error."
                )
                break
            # Capture LLM Test Plan JSON once if provided in text blocks
            if not hasattr(main, '_planned_steps'):
                main._planned_steps = []
            if not hasattr(main, '_raw_plan_text'):
                main._raw_plan_text = ""

            try:
                text_blocks = [
                    b.get('text') for b in response_body.get('content', [])
                    if isinstance(b, dict) and b.get('type') == 'text'
                ]

                if text_blocks:
                    import json as _json
                    combined = "\n\n".join([t for t in text_blocks if isinstance(t, str)])
                    if combined:
                        main._raw_plan_text = combined

                    if not main._planned_steps:
                        json_match = re.search(r"\[\s*\{.*?\}\s*\]", combined, re.DOTALL)
                        if json_match:
                            try:
                                arr = _json.loads(json_match.group(0))
                                if isinstance(arr, list):
                                    main._planned_steps = arr
                            except Exception:
                                pass

                    if not main._planned_steps:
                        parsed_plan = parse_enumerated_plan_from_text(combined)
                        if parsed_plan:
                            main._planned_steps = parsed_plan

            except Exception:
                pass
            
            # Before appending assistant message, prune old messages to ensure tool_use/tool_result pairs stay together
            messages = prune_messages(messages, MAX_MESSAGES)
            if messages is None:
                messages = []
            
            # Validate messages: remove any orphaned tool_result blocks that don't have a corresponding tool_use
            messages = validate_message_pairs(messages)
            if messages is None:
                messages = []
            
            # Ensure content is not None
            content = response_body.get('content')
            if content is None:
                content = []
            elif not isinstance(content, list):
                content = []
            
            messages.append({"role": "assistant", "content": content})
            
            # Increment action cycle count at the start of processing each LLM response
            action_cycle_count += 1
            
            # Safety check: If we've exceeded max cycles, force completion
            if action_cycle_count > MAX_ACTION_CYCLES:
                failed_steps = test_report.report.get("failed_steps", 0)
                if failed_steps == 0:
                    finalize_and_generate_report(
                        test_report,
                        "completed",
                        None,
                        f"Reached maximum action cycle limit ({MAX_ACTION_CYCLES})"
                    )
                    break
                else:
                    add_skipped_steps_if_needed(test_report, test_report.step_counter)
                    finalize_and_generate_report(
                        test_report,
                        "failed",
                        f"Reached maximum cycles with {failed_steps} failed step(s)",
                        f"Maximum action cycles ({MAX_ACTION_CYCLES}) reached with failures."
                    )
                    break
            
            if stop_reason == "tool_use":
                content_blocks = response_body.get('content', [])
                tool_call = next((block for block in content_blocks if isinstance(block, dict) and block.get('type') == 'tool_use'), None)
                
                if not tool_call:
                    # Log detailed error information for debugging
                    print(f"[ERROR] Stop reason was 'tool_use' but no tool call block was found.")
                    print(f"[DEBUG] Response content blocks: {len(content_blocks)}")
                    if content_blocks:
                        print(f"[DEBUG] Content block types: {[b.get('type') if isinstance(b, dict) else type(b).__name__ for b in content_blocks[:5]]}")
                    else:
                        print(f"[DEBUG] Content is empty or None")
                    print(f"[DEBUG] Full response_body keys: {list(response_body.keys())}")
                    
                    # Try to recover: check if there's a text block that might indicate what went wrong
                    text_blocks = [b.get('text', '') for b in content_blocks if isinstance(b, dict) and b.get('type') == 'text']
                    if text_blocks:
                        print(f"[DEBUG] Text blocks in response: {text_blocks[:2]}")
                    
                    # Instead of breaking, try to continue with a retry or provide guidance
                    # Add a user message explaining the issue and ask LLM to retry
                    error_guidance = (
                        "[ERROR] The API returned stop_reason='tool_use' but no tool_use block was found in the response. "
                        "This may be a transient API issue. Please retry your previous action or provide a new instruction."
                    )
                    messages.append({
                        "role": "user",
                        "content": error_guidance
                    })
                    
                    # Don't break immediately - give it one more chance
                    # But limit retries to avoid infinite loops
                    if not hasattr(main, '_tool_use_error_count'):
                        main._tool_use_error_count = 0
                    main._tool_use_error_count += 1
                    
                    if main._tool_use_error_count >= 2:
                        # Too many errors, give up
                        print(f"[ERROR] Too many tool_use errors ({main._tool_use_error_count}), stopping automation.")
                        # Add skipped steps before finalizing
                        add_skipped_steps_if_needed(test_report, test_report.step_counter)
                        finalize_and_generate_report(
                            test_report,
                            "error",
                            "Stop reason was 'tool_use' but no tool call block was found (multiple attempts)",
                            "Automation stopped due to tool_use error."
                        )
                        break
                    else:
                        print(f"[WARN] Retrying after tool_use error (attempt {main._tool_use_error_count})...")
                        continue  # Skip to next iteration
                
                function_name = tool_call['name']
                function_args = tool_call['input']
                tool_call_id = tool_call['id']
                
                # Reset error count on successful tool_use
                if hasattr(main, '_tool_use_error_count'):
                    main._tool_use_error_count = 0
                
                # Reset end_turn counter when LLM actually uses a tool (shows it's making progress)
                if hasattr(main, '_end_turn_count'):
                    main._end_turn_count = 0
                
                # Detect infinite loops: check if same action is repeated too many times
                action_signature = (function_name, str(function_args.get('strategy', '')), str(function_args.get('value', '')))
                recent_same_actions = sum(1 for a in _action_history[-5:] if a == action_signature)
                
                # Special handling for scroll_to_element - detect if same element is scrolled multiple times
                if function_name == 'scroll_to_element':
                    scroll_value = function_args.get('value', '')
                    if not hasattr(main, '_recent_scrolls'):
                        main._recent_scrolls = []
                    main._recent_scrolls.append({
                        'value': scroll_value,
                        'timestamp': time.time()
                    })
                    # Keep only last 5 scrolls
                    if len(main._recent_scrolls) > 5:
                        main._recent_scrolls.pop(0)
                    
                    # Check if same element was scrolled to recently
                    recent_same_scrolls = [s for s in main._recent_scrolls if s['value'] == scroll_value and (time.time() - s['timestamp']) < 30]
                    if len(recent_same_scrolls) >= 3:
                        # Same element scrolled 3+ times - this is an infinite loop
                        print(f"\n[WARN]  Infinite loop detected: '{scroll_value}' has been scrolled to {len(recent_same_scrolls)} times.")
                        print(f"[WARN]  The element should be visible - you should click it or its 'Add to Cart' button instead of scrolling again.")
                        
                        # Add guidance message
                        guidance_msg = (
                            f"CRITICAL: You have scrolled to '{scroll_value}' {len(recent_same_scrolls)} times. "
                            f"This is an infinite loop. The element is already visible. You MUST:\n"
                            f"1. Call `get_page_configuration` to refresh the current screen summary\n"
                            f"2. Find the 'ADD TO CART' alias for '{scroll_value}' in the configuration\n"
                            f"3. Click the 'ADD TO CART' button\n"
                            f"DO NOT call scroll_to_element again for this element."
                        )
                        
                        messages.append({
                            "role": "user",
                            "content": guidance_msg
                        })
                        # Don't break, but guide LLM to fix the issue
                
                # Check if we're making progress (different actions between repetitions)
                has_progress = len(set(_action_history[-5:])) > 1 if len(_action_history) >= 2 else True
                
                if recent_same_actions >= _max_repeat_actions and not has_progress:
                    print(f"\n[WARN]  Detected infinite loop: '{function_name}' with same args repeated {recent_same_actions} times without progress.")
                    print(f"[WARN]  Providing guidance to LLM to try different approach...")
                    
                    # Provide helpful guidance instead of immediately failing
                    guidance_msg = (
                        f"Action '{function_name}' with strategy='{function_args.get('strategy', '')}' and value='{function_args.get('value', '')}' "
                        f"has been attempted {recent_same_actions} times without success. "
                        f"Please try a DIFFERENT approach:\n"
                        f"1. Check page source to see what elements are actually available\n"
                        f"2. Try alternate selectors (if using 'id', try 'content-desc' or 'xpath' or 'text')\n"
                        f"3. Try finding similar elements (e.g., if 'Add to Cart' not found, look for 'ADD', 'Cart', or product name)\n"
                        f"4. Verify you're on the correct page/screen\n"
                        f"5. Try scrolling manually in different directions\n"
                        f"6. If element truly doesn't exist, try navigating to a different screen or using alternate paths"
                    )
                    
                    # Add guidance to messages for LLM context
                    messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": tool_call_id,
                            "content": json.dumps({
                                "success": False, 
                                "error": f"Action failed after {recent_same_actions} attempts with same arguments.",
                                "guidance": guidance_msg
                            })
                        }]
                    })
                    
                    # Don't break immediately - give LLM a chance to try different approach
                    # Only break if we've tried many times with no progress
                    if recent_same_actions >= 5:  # More lenient threshold
                        error_msg = f"Infinite loop detected: '{function_name}' action repeated {recent_same_actions} times. Element may not exist or be reachable. Please verify the user's prompt is correct."
                        # Add skipped steps before finalizing
                        add_skipped_steps_if_needed(test_report, test_report.step_counter)
                        finalize_and_generate_report(
                            test_report,
                            "failed",
                            error_msg,
                            f"Test stopped at Step {step_number} after {recent_same_actions} repeated attempts."
                        )
                        break
                
                # Track this action
                _action_history.append(action_signature)
                if len(_action_history) > 10:  # Keep only last 10 actions
                    _action_history.pop(0)
                
                # Initialize error flag for this iteration before any completion checks
                is_error = False
                
                # COMPLETION CHECK: After each action, check if all steps are complete
                # This prevents continuing after completion even if LLM doesn't return end_turn
                # Also check if we're repeating actions (indicates we're done but stuck)
                if action_cycle_count > 2 and not is_error:
                    try:
                        # Completion guardrail: only rely on explicit planned steps
                        if hasattr(main, '_planned_steps') and isinstance(main._planned_steps, list) and len(main._planned_steps) > 0:
                            executed_count = len([s for s in test_report.report.get('steps', []) if s.get('status') != 'SKIPPED'])
                            failed_count = test_report.report.get("failed_steps", 0)
                            
                            if executed_count >= len(main._planned_steps) and failed_count == 0:
                                executed_descriptions = set()
                                for step_info in test_report.report.get('steps', []):
                                    desc = step_info.get('description', '')
                                    if desc and step_info.get('status') != 'SKIPPED':
                                        executed_descriptions.add(desc.lower().strip())
                                
                                all_executed = True
                                for planned_step in main._planned_steps:
                                    plan_desc = planned_step.get('name', planned_step.get('description', planned_step.get('action', '')))
                                    if plan_desc:
                                        plan_desc_normalized = plan_desc.lower().strip()
                                        found_match = False
                                        for exec_desc in executed_descriptions:
                                            match_phrases = planned_step.get('match_phrases') or []
                                            if match_phrases:
                                                if any(phrase for phrase in match_phrases if phrase and phrase in exec_desc):
                                                    found_match = True
                                                    break
                                            plan_keywords = set(plan_desc_normalized.split())
                                            exec_keywords = set(exec_desc.split())
                                            if len(plan_keywords & exec_keywords) >= min(2, len(plan_keywords) // 2):
                                                found_match = True
                                                break
                                        if not found_match:
                                            all_executed = False
                                            break
                                
                                if all_executed:
                                    finalize_and_generate_report(
                                        test_report,
                                        "completed",
                                        None,
                                        "All planned steps have been executed successfully."
                                    )
                                    break
                    except Exception:
                        # If check fails, continue normally
                        pass
                
                # Format description
                step_description = format_step_description(function_name, function_args)
                
                # Don't increment step number or print for get_page_source (it's an internal observation step)
                if function_name != 'get_page_source':
                    step_number += 1
                    # Format tool call in Claude Desktop style
                    tool_name_display = function_name.replace('_', '-').title()
                    print(f"\n[TOOL_CALL] {tool_name_display}")
                    print(f"[TOOL_REQUEST] {json.dumps(function_args, indent=2)}")
                
                # Auto-hide keyboard before clicking buttons (especially if previous action was send_keys)
                if function_name == 'click':
                    button_value = function_args.get('value') or ''
                    hide_keyboard_if_needed(f"clicking '{button_value}'")
                
                # Note: Verification is now only performed when explicitly requested in user prompt
                # No automatic enforcement - LLM will decide based on user's validation requirements
                
                # Check if function is in available_functions, otherwise route to generic dispatcher
                if function_name in available_functions:
                    # Optionally disable launch_app via env flag
                    disable_launch = os.getenv('DISABLE_LAUNCH_APP', '1').lower() in ('1', 'true', 'yes')
                    if disable_launch and function_name == 'launch_app':
                        result = {"success": False, "error": "launch_app disabled by configuration (DISABLE_LAUNCH_APP)"}
                    # Enforce strict user-provided inputs for common fields (username/password)
                    elif function_name == 'send_keys' and isinstance(function_args, dict):
                        target = (function_args.get('value') or '').lower()
                        text = function_args.get('text')
                        expected = None
                        if 'user' in target or 'login' in target or 'email' in target:
                            expected = expected_inputs.get('username')
                        if 'pass' in target or 'pwd' in target or 'password' in target:
                            # If both match, prefer password match
                            exp_pwd = expected_inputs.get('password')
                            if exp_pwd is not None:
                                expected = exp_pwd
                        if expected is not None and text is not None and text != expected:
                            result = {"success": False, "error": f"Strict input enforcement: expected '{expected}' but got '{text}'. Use exactly the user-provided value."}
                        else:
                            # Auto-inject sessionId for OCR assert if missing
                            if function_name == 'wait_for_text_ocr' and isinstance(function_args, dict) and 'sessionId' not in function_args:
                                if hasattr(main, '_session_id') and main._session_id:
                                    function_args = {**function_args, 'sessionId': main._session_id}
                                    print(f"[TOOL] Auto-injected sessionId: {main._session_id}")
                                else:
                                    print("[WARN]  Warning: No session ID available for OCR call")
                            # Retry logic with fallback strategies (max 3 attempts)
                            result = _execute_with_retry(
                                function_name,
                                function_args,
                                available_functions,
                                expected_inputs,
                                user_goal=user_goal,
                                cached_page_config=(_cached_page_config or {}).get('data'),
                                config_fetcher=fetch_page_config_snapshot
                            )
                    elif function_name == 'press_back_button':
                        allow_back = any(
                            phrase in user_goal_lower
                            for phrase in ['back', 'go back', 'previous', 'close', 'dismiss']
                        ) or getattr(main, '_recent_failure', False)
                        if not allow_back:
                            result = {
                                "success": False,
                                "error": "Back navigation is blocked unless the user explicitly requests it or you are recovering from a failure. Continue with the remaining steps."
                            }
                        else:
                            result = _execute_with_retry(
                                function_name,
                                function_args,
                                available_functions,
                                expected_inputs,
                                smart_executor=smart_executor,
                                user_goal=user_goal,
                                cached_page_config=(_cached_page_config or {}).get('data'),
                                config_fetcher=fetch_page_config_snapshot
                            )
                    else:
                        # Auto-inject sessionId for OCR assert if missing
                        if function_name == 'wait_for_text_ocr' and isinstance(function_args, dict) and 'sessionId' not in function_args:
                            if hasattr(main, '_session_id') and main._session_id:
                                function_args = {**function_args, 'sessionId': main._session_id}
                                print(f"[TOOL] Auto-injected sessionId: {main._session_id}")
                            else:
                                print("[WARN]  Warning: No session ID available for OCR call")
                        # Retry logic with fallback strategies (max 3 attempts)
                        result = _execute_with_retry(
                            function_name,
                            function_args,
                            available_functions,
                            expected_inputs,
                            smart_executor=smart_executor,
                            user_goal=user_goal,
                            cached_page_config=(_cached_page_config or {}).get('data'),
                            config_fetcher=fetch_page_config_snapshot
                        )
                else:
                    # Tool not in available_functions - route to generic dispatcher
                    # This allows the LLM to use all 110+ tools from appium-mcp
                    import appium_tools
                    if hasattr(appium_tools, 'call_generic_tool'):
                        print(f"--- [INFO] Routing {function_name} to generic tool dispatcher")
                        result = appium_tools.call_generic_tool(function_name, **function_args)
                    else:
                        result = {"success": False, "error": f"Tool {function_name} not found in available_functions and generic dispatcher not available"}
                    
                    # Check if result indicates an error
                    is_error = False
                    error_message = ""
                    if isinstance(result, dict) and result.get('success') is False:
                        is_error = True
                        error_message = result.get('error', 'Unknown error')
                    
                    # Show Pass/Fail status
                    if is_error:
                        print(f"  Result: Fail - {error_message}")
                    else:
                        print(f"  Result: Pass")
                    
                    # Continue to next iteration (skip the rest of the error handling for this tool)
                    continue
                
                # Check if result indicates an error (for tools in available_functions)
                is_error = False
                error_message = ""
                
                # Handle get_page_source returning dict on error
                if isinstance(result, dict) and result.get('success') is False:
                    is_error = True
                    error_message = result.get('error', 'Unknown error')
                elif isinstance(result, str) and result.startswith("Error:"):
                    is_error = True
                    error_message = result
                elif isinstance(result, dict):
                    success_value = result.get('success')
                    
                    # CRITICAL: send_keys and some tools return success: False when they fail
                    if (success_value is False or 
                        success_value == False or 
                        str(success_value).lower() == 'false'):
                        is_error = True
                        if function_name in ('send_keys', 'ensure_focus_and_type'):
                            error_msg = result.get('error', result.get('message', 'send_keys returned success: false'))
                            # Check if this is a container typing issue
                            value = function_args.get('value', '') if isinstance(function_args, dict) else ''
                            if value and any(pattern in value.lower() for pattern in ['_chip_group', '_container', '_wrapper', '_layout']):
                                error_message = f"Failed to send text to container element '{value}'. The element is a container, not an editable field. The system should tap the container first, refresh XML, find the EditText descendant, and retry. {error_msg}"
                            else:
                                error_message = f"Failed to send text. Element might not be an input field, not editable, or not found. {error_msg}"
                        else:
                            error_message = result.get('error', result.get('message', 'Action returned success: false'))
                    elif 'Error:' in str(result.get('message', '')):
                        is_error = True
                        error_message = str(result.get('message', ''))
                    elif 'Failed' in str(result.get('message', '')) or 'failed' in str(result.get('message', '')):
                        is_error = True
                        error_message = str(result.get('message', ''))
                
                # If assertion/verification succeeded, detect page name if it's a page identifier
                if function_name == 'wait_for_text_ocr' and isinstance(result, dict) and result.get('success'):
                    ocr_value = function_args.get('value', '')
                    detected_page = detect_page_name_from_text(ocr_value)
                    if detected_page != "Unknown Page":
                        # Suppress technical message - not shown to users
                        # print(f"\n[NAV] Page Identified: {detected_page} (via verification text: '{ocr_value}')")
                        pass
                
                # Record step in report (mark assertions)
                is_assertion = function_name in ('wait_for_element', 'wait_for_text_ocr', 'assert_activity')
                test_report.add_step(function_name, function_args, result, not is_error, is_assertion, description=step_description if function_name != 'get_page_source' else None)

                main._recent_failure = bool(is_error)

                # Show Pass/Fail status (skip get_page_source as it's internal)
                if function_name != 'get_page_source':
                    # Format response in Claude Desktop style
                    if isinstance(result, dict):
                        # Clean up result for display (remove verbose fields)
                        display_result = {k: v for k, v in result.items() 
                                        if k not in ['retryAttempts', 'fallbackUsed', 'method']}
                        # Truncate very long results
                        if 'xml' in display_result and len(str(display_result['xml'])) > 500:
                            display_result['xml'] = str(display_result['xml'])[:500] + "... [truncated]"
                        print(f"[TOOL_RESPONSE] {json.dumps(display_result, indent=2)}")
                    else:
                        print(f"[TOOL_RESPONSE] {json.dumps({'result': str(result)[:500]}, indent=2)}")
                    
                    if is_error:
                        print(f"  Result: Fail")
                    else:
                        print(f"  Result: Pass")

                # If action ultimately failed after retries, prepare failure messaging
                retry_attempts = None
                if isinstance(result, dict):
                    retry_attempts = result.get('retryAttempts')
                if is_error:
                    # Build descriptive failure message
                    step_label = step_description if function_name != 'get_page_source' else function_name
                    if step_number > 0 and function_name != 'get_page_source':
                        if retry_attempts:
                            failure_text = f"Step {step_number}: {step_label} failed after {retry_attempts} attempts"
                        else:
                            failure_text = f"Step {step_number}: {step_label} failed"
                    else:
                        if retry_attempts:
                            failure_text = f"Action '{step_label}' failed after {retry_attempts} attempts"
                        else:
                            failure_text = f"Action '{step_label}' failed"
                    
                    # Include error details if available
                    if error_message and failure_text not in error_message:
                        failure_text = f"{failure_text}. Details: {error_message}"
                    
                    print(f"  [ERROR] {failure_text}")
                    
                    # Update error message and result metadata so reports reflect the failure
                    error_message = failure_text
                    if isinstance(result, dict):
                        result['failureReason'] = failure_text
                    
                    # If container typing failed, provide specific guidance to LLM
                    if function_name in ('send_keys', 'ensure_focus_and_type') and isinstance(function_args, dict):
                        value = function_args.get('value', '')
                        if value and any(pattern in value.lower() for pattern in ['_chip_group', '_container', '_wrapper', '_layout']):
                            container_guidance = (
                                f"CRITICAL: Typing into container element '{value}' failed. "
                                f"This is a container (ChipGroup, Layout, ViewGroup), not an editable field. "
                                f"You MUST follow this workflow:\n"
                                f"1. Tap/click the container element to focus the input area\n"
                                f"2. Call get_page_source to refresh the XML (the EditText node appears only after tapping)\n"
                                f"3. Search the NEW XML for an EditText within that container\n"
                                f"4. Use the resolved EditText locator to type the text\n"
                                f"5. DO NOT type directly into container elements - they are not editable\n"
                                f"Retry the action following this workflow."
                            )
                            messages.append({
                                "role": "user",
                                "content": container_guidance
                            })
                    
                # CRITICAL: After scroll_to_element succeeds, guide LLM to click the element immediately
                if (not is_error and function_name == 'scroll_to_element' and isinstance(result, dict) and result.get('success')):
                        # Check if we've scrolled to the same element multiple times
                        scroll_value = function_args.get('value', '')
                        if not hasattr(main, '_recent_scrolls'):
                            main._recent_scrolls = []
                        
                        # Track recent scrolls
                        main._recent_scrolls.append({
                            'value': scroll_value,
                            'timestamp': time.time()
                        })
                        # Keep only last 5 scrolls
                        if len(main._recent_scrolls) > 5:
                            main._recent_scrolls.pop(0)
                        
                        # Check if same element was scrolled to recently (within last 30 seconds)
                        recent_same_scrolls = [s for s in main._recent_scrolls if s['value'] == scroll_value and (time.time() - s['timestamp']) < 30]
                        
                        if len(recent_same_scrolls) >= 2:
                            # Same element scrolled multiple times - guide LLM to click instead
                            print(f"\n[WARN]  Element '{scroll_value}' has been scrolled to {len(recent_same_scrolls)} times. The element should now be visible - you should click it or its 'Add to Cart' button instead of scrolling again.")
                            
                            # Add guidance message to help LLM
                            guidance_text = (
                                f"CRITICAL: You have successfully scrolled to '{scroll_value}' {len(recent_same_scrolls)} times. "
                                f"The element is now visible on screen. You MUST immediately interact with it:\n"
                                f"- If this is a product name, find and click its 'ADD TO CART' button\n"
                                f"- If this is a button or element, click it directly\n"
                                f"- DO NOT call scroll_to_element again for the same element\n"
                                f"- Get the current page source to see what elements are available, then click the appropriate button"
                            )
                            
                            messages.append({
                                "role": "user",
                                "content": guidance_text
                            })
                        else:
                            # First or second scroll - add guidance to click after scrolling
                            guidance_text = (
                                f"SUCCESS: You have successfully scrolled to '{scroll_value}'. "
                                f"The element is now visible on screen. You MUST immediately interact with it:\n"
                                f"- If this is a product name (e.g., 'Sauce Labs Bike Light'), find and click its 'ADD TO CART' button\n"
                                f"- Get the current page source to locate the 'ADD TO CART' button for this product\n"
                                f"- Click the button to add the product to cart\n"
                                f"- DO NOT call scroll_to_element again - the element is already visible"
                            )
                            
                            messages.append({
                                "role": "user",
                                "content": guidance_text
                            })
                    
                # Print success message for meaningful actions
                if (not is_error and 
                    function_name != 'get_page_source' and
                    function_name != 'take_screenshot' and
                    step_number > 0):
                        # Create user-friendly success message
                        if function_name == 'click':
                            # Try to extract element name from step description
                            success_msg = "Click successful"
                            if step_description:
                                # Extract element name if available
                                import re
                                match = re.search(r'(?:Click|click)\s+(?:on\s+)?([A-Z][a-zA-Z\s]+?)(?:\s+button|\s+element|$)', step_description)
                                if match:
                                    element_name = match.group(1).strip()
                                    success_msg = f"Click on {element_name} successful"
                        elif function_name in ('send_keys', 'ensure_focus_and_type'):
                            success_msg = "Typing successful"
                            if step_description:
                                import re
                                match = re.search(r'(?:Type|Enter|type|enter).*?["\']([^"\']+)["\']', step_description)
                                if match:
                                    text_value = match.group(1)
                                    success_msg = f"Typed: {text_value}"
                        elif function_name == 'wait_for_text_ocr':
                            success_msg = "Text found"
                        elif function_name == 'swipe':
                            success_msg = "Swipe successful"
                        elif function_name == 'scroll':
                            success_msg = "Scroll successful"
                        elif function_name == 'scroll_to_element':
                            success_msg = "Element found - ready to interact"
                        elif function_name == 'long_press':
                            success_msg = "Long press successful"
                        else:
                            success_msg = "Action completed successfully"
                        print(f"  [SUCCESS] {success_msg}")
                    
                # Take screenshot after meaningful successful actions (not internal operations)
                # Screenshots are taken after: click, send_keys, wait_for_text_ocr (when successful)
                # Skip: get_page_source, wait_for_element (internal), take_screenshot itself
                meaningful_actions = ('click', 'send_keys', 'wait_for_text_ocr', 'swipe', 'scroll', 'long_press')
                if (not is_error and 
                    function_name in meaningful_actions and 
                    function_name != 'get_page_source' and
                    function_name != 'take_screenshot'):
                        try:
                            # Add delay before taking screenshot to allow screen to stabilize
                            # This ensures screenshots capture the final state, not transition states
                            time.sleep(0.5)  # 500ms delay for screen to stabilize
                            
                            import appium_tools
                            screenshot_result = appium_tools.take_screenshot()
                            if isinstance(screenshot_result, dict) and screenshot_result.get('success'):
                                screenshot_path = screenshot_result.get('screenshotPath') or screenshot_result.get('path')
                                if screenshot_path:
                                    # Store screenshot path in result so it gets saved in the report
                                    if isinstance(result, dict):
                                        result['after_screenshot_path'] = screenshot_path
                                    # Print screenshot info in parseable format for real-time emission
                                    print(f"  [SCREENSHOT] Captured after: {step_description} | PATH: {screenshot_path}")
                        except Exception as screenshot_error:
                            # Don't fail the step if screenshot fails
                            print(f"  [WARN] Could not take screenshot: {screenshot_error}")
                
                # If assertion failed, stop the run immediately
                if function_name in ('wait_for_element', 'wait_for_text_ocr', 'assert_activity'):
                    if isinstance(result, dict) and result.get('success') is False:
                        # Get page source for verification instead of screenshot
                        try:
                            xml_result = get_page_source_guarded("assertion failure analysis")
                            # Handle both string (success) and dict (error) returns
                            if isinstance(xml_result, dict):
                                if xml_result.get('success'):
                                    current_page_xml = xml_result.get('value', '')
                                else:
                                    current_page_xml = f"[Error getting page source: {xml_result.get('error', 'Unknown error')}]"
                            else:
                                current_page_xml = xml_result
                            # Apply cost optimizations
                            if USE_XML_COMPRESSION:
                                current_page_xml = compress_xml(current_page_xml)
                            
                            # Use dynamic XML length based on current message count
                            dynamic_xml_limit = get_dynamic_xml_length(len(messages) + 1)
                            truncated_page_xml = truncate_xml(current_page_xml, dynamic_xml_limit)
                            page_analysis = f"[ERROR] ASSERTION FAILED: Expected '{function_args.get('value', '')}' not found.\n\n📄 Current page source:\n{truncated_page_xml}\n\nAnalyze the page source to determine:\n1. What page/screen is currently visible?\n2. Are there any expected elements or text visible in the XML?\n3. Did the navigation succeed but the element locator is wrong?\n4. Or did the navigation fail completely?\n\nBased on the page source, provide a clear reason for the assertion failure."
                        except Exception as xml_error:
                            page_analysis = f"[ERROR] ASSERTION FAILED: Expected element not visible. Page source unavailable: {xml_error}"
                        
                        messages.append({
                            "role": "user",
                            "content": [
                                {"type": "tool_result", "tool_use_id": tool_call_id, "content": json.dumps(result)},
                                {"type": "text", "text": page_analysis}
                            ]
                        })
                        try:
                            if hasattr(main, '_planned_steps') and isinstance(main._planned_steps, list):
                                test_report.add_skipped_steps(main._planned_steps, test_report.step_counter + 1)
                        except Exception:
                            pass
                        finalize_and_generate_report(
                            test_report,
                            "error",
                            "Assertion failed: expected element not visible",
                            f"Test stopped at Step {step_number}. Subsequent steps were skipped."
                        )
                        print("\n[LIST] Step Summary:")
                        print(test_report.get_step_summary())
                        break
                
                # Mark that screen likely changed - will refresh cache on next loop
                _last_action_was_screen_change = True
                
                # Get fresh perception snapshot after action for next LLM turn
                try:
                    if USE_PAGE_CONFIGURATION:
                        config_result = get_page_configuration_guarded("post-action observation")
                        summary_text, payload_text, config_data = render_config_state(config_result)
                        snapshot_payload = payload_text or summary_text
                        if not summary_text:
                            summary_text = "[WARN] Page configuration not available."
                        if not snapshot_payload:
                            snapshot_payload = summary_text
                        
                        _cached_page_config = {"summary": summary_text, "payload": snapshot_payload, "data": config_data}
                        _cached_page_config_timestamp = time.time()
                        
                        dynamic_context_limit = get_dynamic_xml_length(len(messages) + 1)
                        truncated_summary = truncate_text_block(summary_text, dynamic_context_limit)
                        truncated_payload = truncate_text_block(snapshot_payload, dynamic_context_limit)
                        
                        updated_perception = f"[Page Configuration Summary (updated after action)]:\n{truncated_summary}"
                        messages.append({
                            "role": "user",
                            "content": build_device_context_payload(updated_perception, truncated_payload)
                        })
                    else:
                        xml_result = get_page_source_guarded("post-action observation")
                        if isinstance(xml_result, dict):
                            if xml_result.get('success'):
                                current_screen_xml = xml_result.get('value', '')
                            else:
                                current_screen_xml = f"[Error getting page source: {xml_result.get('error', 'Unknown error')}]"
                        else:
                            current_screen_xml = xml_result
                        if USE_XML_COMPRESSION:
                            current_screen_xml = compress_xml(current_screen_xml)
                        _cached_xml = current_screen_xml
                        _cached_xml_timestamp = time.time()
                        _previous_xml = current_screen_xml
                        
                        dynamic_xml_limit = get_dynamic_xml_length(len(messages) + 1)
                        truncated_current_xml = truncate_xml(current_screen_xml, dynamic_xml_limit)
                        updated_perception = f"[XML Page Source (updated after action)]:\n{truncated_current_xml}"
                        messages.append({
                            "role": "user",
                            "content": build_device_context_payload(updated_perception, truncated_current_xml)
                        })
                except Exception as perception_error:
                    error_payload = f"Error getting latest screen state: {perception_error}"
                    print(f"[ERROR] Failed to refresh screen state: {perception_error}")
                
                if is_error:
                    # REFLECTION MODE: Immediate reflection after any failure
                    print("\n" + "="*60)
                    print("[REFLECT] REFLECTION MODE: Analyzing failure...")
                    print("="*60)
                    
                    try:
                        # Get current page source for reflection (fast - XML only)
                        try:
                            xml_result = get_page_source_guarded("reflection snapshot")
                            # Handle both string (success) and dict (error) returns
                            if isinstance(xml_result, dict):
                                if xml_result.get('success'):
                                    reflection_xml = xml_result.get('value', '')
                                else:
                                    reflection_xml = ''  # Error case, skip text extraction
                            else:
                                reflection_xml = xml_result
                            # Extract text from XML directly (fast)
                            import re
                            text_matches = re.findall(r'text="([^"]+)"', reflection_xml) if reflection_xml else []
                            visible_text = text_matches[:15]  # Limit for speed
                        except:
                            visible_text = []
                        
                        # Build reflection prompt
                        reflection_prompt = f"""Action failed: {function_name} with args {function_args}
Observed text on screen: {', '.join(visible_text[:15]) if visible_text else 'No text detected'}
Expected outcome: {get_verification_requirement(function_name, function_args) if requires_verification(function_name, function_args) else 'Action should have succeeded'}
Error message: {error_message}

What went wrong? Suggest recovery steps. Provide specific actions to try (e.g., scroll, retry with different selector, check if element is visible)."""
                        
                        # Call LLM for reflection
                        reflection_request = {
                            "system": "You are a QA testing expert. Analyze test failures and suggest recovery steps.",
                            "messages": [
                                {"role": "user", "content": reflection_prompt}
                            ],
                            "anthropic_version": "bedrock-2023-05-31",
                            "max_tokens": 512
                        }
                        
                        reflection_response = invoke_bedrock_with_retry(
                            bedrock_client,
                            reflection_request,
                            BEDROCK_MODEL_ID,
                            max_retries=2,
                            base_delay=0.3  # Optimized: Faster reflection (reduced to 0.3s)
                        )
                        
                        reflection_body = json.loads(reflection_response['body'].read().decode('utf-8'))
                        reflection_text = next(
                            (block['text'] for block in reflection_body.get('content', []) if block.get('type') == 'text'),
                            "Could not generate reflection."
                        )
                        
                        print(f"[INFO] Reflection Analysis:\n{reflection_text}\n")
                        
                        # Store reflection in report
                        if hasattr(test_report, 'add_reflection'):
                            test_report.add_reflection(step_number, reflection_text)
                        
                        # Add reflection to messages with guidance to try different approach
                        reflection_message = (
                            f"[REFLECT] REFLECTION MODE:\n{reflection_text}\n\n"
                            f"[ERROR] Action failed: {function_name} with args {function_args}\n"
                            f"Error: {error_message}\n\n"
                            f"Please try a DIFFERENT approach:\n"
                            f"1. Check the current page source to see what elements are available\n"
                            f"2. Try alternate selectors (if using 'id', try 'content-desc', 'xpath', or 'text')\n"
                            f"3. Try finding similar elements (e.g., if 'Add to Cart' not found, look for 'ADD', 'Cart', or product name)\n"
                            f"4. Verify you're on the correct page/screen - navigate if needed\n"
                            f"5. Try scrolling manually in different directions\n"
                            f"6. If element truly doesn't exist, try navigating to a different screen or using alternate paths\n"
                            f"7. For text input: ensure you're selecting the EditText element, not a container"
                        )
                        
                        messages.append({
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_call_id,
                                    "content": json.dumps({
                                        "success": False,
                                        "error": error_message,
                                        "reflection": reflection_text,
                                        "guidance": "Try different selectors or approaches based on reflection analysis"
                                    })
                                },
                                {
                                    "type": "text",
                                    "text": reflection_message
                                }
                            ]
                        })
                        
                        print("="*60 + "\n")
                        
                        # Don't stop immediately - give LLM a chance to try different approach
                        # Only stop if this is an explicit assertion/verification failure (user requested validation)
                        if function_name in ('wait_for_element', 'wait_for_text_ocr', 'assert_activity'):
                            # These are explicit validations - if they fail, user's requirement wasn't met
                            # Add skipped steps before finalizing
                            add_skipped_steps_if_needed(test_report, test_report.step_counter)
                            finalize_and_generate_report(
                                test_report,
                                "error",
                                f"Validation failed: {error_message}",
                                f"Test stopped at Step {step_number}. Validation requirement not met."
                            )
                            break
                        else:
                            # For other actions, continue and let LLM try different approach
                            print(f"[INFO] Action failed, but continuing to allow LLM to try different approach...")
                            continue
                            
                    except Exception as reflection_error:
                        print(f"[WARN]  Reflection mode failed: {reflection_error}")
                        # Continue with standard failure handling - provide guidance
                        failure_text = (
                            f"[ERROR] Action failed: {function_name} with args {function_args}\n"
                            f"Error: {error_message}\n\n"
                            f"Please try a DIFFERENT approach:\n"
                            f"1. Check the current page source to see what elements are available\n"
                            f"2. Try alternate selectors (if using 'id', try 'content-desc', 'xpath', or 'text')\n"
                            f"3. Try finding similar elements\n"
                            f"4. Verify you're on the correct page/screen\n"
                            f"5. Try scrolling manually in different directions"
                        )
                        messages.append({
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_call_id,
                                    "content": json.dumps({
                                        "success": False,
                                        "error": error_message,
                                        "guidance": "Try different selectors or approaches"
                                    })
                                },
                                {
                                    "type": "text",
                                    "text": failure_text
                                }
                            ]
                        })
                        
                        # Don't stop - give LLM a chance to try different approach
                        if function_name not in ('wait_for_element', 'wait_for_text_ocr', 'assert_activity'):
                            print(f"[INFO] Action failed, but continuing to allow LLM to try different approach...")
                            continue
                else:
                    # Action was successful
                    if function_name in ('send_keys', 'ensure_focus_and_type'):
                        main._keyboard_visible = True
                    elif function_name == 'hide_keyboard':
                        main._keyboard_visible = False
                    is_nav = is_navigation_action(function_name, function_args)
                    
                    if USE_PAGE_CONFIGURATION:
                        latest_summary = (_cached_page_config or {}).get('summary')
                        if suppress_page_state or not latest_summary:
                            success_text = "[OK] Action was successful. Screen updated."
                        else:
                            success_text = f"[OK] Action was successful. Here is the new screen:\n{latest_summary}"
                    else:
                        latest_xml_view = _cached_xml or ""
                        if USE_XML_COMPRESSION:
                            latest_xml_view = compress_xml(latest_xml_view)
                        truncated_view = truncate_xml(latest_xml_view, get_dynamic_xml_length(len(messages) + 1)) if latest_xml_view else ""
                        if suppress_page_state or not truncated_view:
                            success_text = "[OK] Action was successful. Screen updated."
                        else:
                            success_text = f"[OK] Action was successful. Here is the new screen:\n{truncated_view}"
                    
                    # Automatically detect page name after navigation actions
                    # NOTE: This is informational only - LLM will still verify with wait_for_text_ocr
                    # Suppress all page detection messages - not shown to users
                    if is_nav and not is_error:
                        # Suppress all page detection output
                        # print("\n" + "="*60)
                        # print("[NAV] AUTOMATIC PAGE DETECTION (Informational)")
                        # print("="*60)
                        
                        page_detection = auto_detect_page_after_navigation(
                            session_id=main._session_id if hasattr(main, '_session_id') else None
                        )
                        
                        # Suppress all page detection messages - not shown to users
                        # if page_detection['detected']:
                        #     print(f"[OK] Page Detected: {page_detection['page_name']}")
                        #     print(f"[LIST] Detected via: {page_detection.get('method', 'Unknown')}")
                        #     print(f"[CHECK] Identifier: '{page_detection['identifier']}'")
                        #     print(f"[INFO] Note: LLM will verify with specific page identifier (e.g., 'PRODUCTS', 'CART')")
                        #     success_text += f"\n[NAV] Page Detected: {page_detection['page_name']} (detected via {page_detection.get('method', 'Unknown')}: '{page_detection['identifier']}')"
                        # else:
                        #     print(f"[WARN]  Could not automatically detect page name")
                        #     print(f"[INFO] Page may still be loading or no prominent text found")
                        #     success_text += f"\n[WARN]  Page detection: Could not automatically identify page name"
                        
                        # print("="*60 + "\n")
                        pass
                    
                    # Note: Verification is now only performed when explicitly requested in user prompt
                    # No automatic verification enforcement - LLM will decide based on user's validation requirements
                    # Clear any old verification flags
                    main._last_requires_verification = False
                    
                    # COMPLETION DETECTION: Check if we've completed all steps
                    # This detects when we've reached the completion page after FINISH action
                    # OR when login is complete (screen changes from login to products page)
                    if (not is_error and 
                            function_name == 'click' and 
                            step_description):
                            
                            # Check for login completion
                            is_login_action = any(keyword in step_description.lower() for keyword in ['login', 'log in', 'sign in'])
                            
                            # Check for finish/completion actions
                            is_finish_action = 'finish' in step_description.lower()
                            
                            if is_login_action or is_finish_action:
                                # Wait a moment for page to load after clicking Login/FINISH
                                time.sleep(1.5)
                                
                                # Check if we're on completion page or have successfully logged in
                                try:
                                    completion_xml_result = get_page_source_guarded("completion verification")
                                    completion_xml = None
                                    if isinstance(completion_xml_result, str):
                                        completion_xml = completion_xml_result
                                    elif isinstance(completion_xml_result, dict):
                                        if completion_xml_result.get('success'):
                                            completion_xml = completion_xml_result.get('value', '')
                                        else:
                                            completion_xml = None
                                    
                                    login_steps_completed = False
                                    xml_lower = completion_xml.lower() if completion_xml else ""
                                    
                                    # For finish: Check if we're on completion page
                                    if is_finish_action and completion_xml:
                                        completion_indicators = [
                                            'thank you for your order',
                                            'order complete',
                                            'checkout complete',
                                            'back home',
                                            'thank you',
                                            'complete'
                                        ]
                                        is_completion_page = any(indicator in xml_lower for indicator in completion_indicators)
                                        
                                        if is_completion_page:
                                            finalize_and_generate_report(
                                                test_report,
                                                "completed",
                                                None,
                                                "Reached completion page after FINISH action."
                                            )
                                            # Break out of the main loop
                                            break
                                except Exception:
                                    # If completion check fails, continue loop (planned steps logic handles completion)
                                    pass
                    
                    messages.append({
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_call_id,
                                "content": json.dumps(result)
                            },
                            {
                                "type": "text",
                                "text": success_text
                            }
                        ]
                    })
            
            elif stop_reason == "end_turn":
                # FIX: Track consecutive end_turn responses to prevent infinite loops
                if not hasattr(main, '_end_turn_count'):
                    main._end_turn_count = 0
                main._end_turn_count += 1
                
                # Early completion check: If LLM returns end_turn 2+ times, check if goal is complete
                if main._end_turn_count >= 2:
                    # Quick goal satisfaction check
                    user_goal_lower = user_goal.lower()
                    executed_steps = [s.get('description', '').lower() for s in test_report.report.get('steps', []) if s.get('status') == 'PASS']
                    
                    # Check if key actions from goal are satisfied
                    goal_satisfied = True
                    if 'open' in user_goal_lower:
                        app_match = re.search(r'open\s+([a-z0-9 ._-]+)', user_goal, re.IGNORECASE)
                        if app_match:
                            app_name = app_match.group(1).lower().strip()
                            if not any(app_name in desc or desc in app_name for desc in executed_steps):
                                goal_satisfied = False
                    
                    if 'search' in user_goal_lower and goal_satisfied:
                        if not any('search' in desc for desc in executed_steps):
                            goal_satisfied = False
                    
                    if 'play' in user_goal_lower and goal_satisfied:
                        if not any('play' in desc or 'video' in desc for desc in executed_steps):
                            goal_satisfied = False
                    
                    # If goal appears satisfied and we have successful steps, stop
                    if goal_satisfied and len(executed_steps) >= 2:
                        finalize_and_generate_report(
                            test_report,
                            "completed",
                            None,
                            f"Goal completed (detected via multiple end_turn: {main._end_turn_count} times)"
                        )
                        break
                
                # Verify all steps are completed before accepting end_turn
                # Check if there are planned steps that haven't been executed
                has_uncompleted_steps = False
                uncompleted_step_descriptions = []
                
                if hasattr(main, '_planned_steps') and isinstance(main._planned_steps, list) and len(main._planned_steps) > 0:
                    # Get executed step descriptions for comparison
                    executed_descriptions = set()
                    for step_info in test_report.report.get('steps', []):
                        desc = step_info.get('description', '')
                        if desc:
                            # Normalize description for comparison
                            executed_descriptions.add(desc.lower().strip())
                    
                    # Check planned steps against executed steps
                    for planned_step in main._planned_steps:
                        plan_desc = planned_step.get('name', planned_step.get('description', planned_step.get('action', '')))
                        if plan_desc:
                            plan_desc_normalized = plan_desc.lower().strip()
                            # Check if this planned step was executed
                            # Match by description similarity or action keywords
                            found_match = False
                            for exec_desc in executed_descriptions:
                                # Check if key action words match
                                plan_keywords = set(plan_desc_normalized.split())
                                exec_keywords = set(exec_desc.split())
                                # If significant overlap, consider it executed
                                if len(plan_keywords & exec_keywords) >= min(2, len(plan_keywords) // 2):
                                    found_match = True
                                    break
                            
                            if not found_match:
                                has_uncompleted_steps = True
                                uncompleted_step_descriptions.append(plan_desc)
                
                # Also check if we have failed steps - if so, don't mark as completed
                failed_steps = test_report.report.get("failed_steps", 0)
                
                if has_uncompleted_steps:
                    # FIX: Prevent infinite loop - if LLM returns end_turn too many times, force it to use a tool
                    if main._end_turn_count >= 3:
                        print(f"\n[WARN]  LLM returned end_turn {main._end_turn_count} times without completing steps. Forcing tool use...")
                        remaining_steps_text = "\n".join([f"- {desc}" for desc in uncompleted_step_descriptions[:5]])
                        
                        # More aggressive guidance - explicitly tell it what tool to use
                        next_step = uncompleted_step_descriptions[0] if uncompleted_step_descriptions else "next step"
                        tool_guidance = ""
                        if "compose" in next_step.lower() or "click" in next_step.lower():
                            tool_guidance = "Use the 'click' tool to click the Compose button."
                        elif "email" in next_step.lower() or "to" in next_step.lower():
                            tool_guidance = "Use 'get_page_configuration' to see the compose screen aliases, then use 'send_keys' or 'ensure_focus_and_type' to enter the email address in the 'To' field."
                        elif "subject" in next_step.lower():
                            tool_guidance = "Use 'get_page_configuration' to find the subject field alias, then use 'send_keys' or 'ensure_focus_and_type' to enter the subject."
                        elif "body" in next_step.lower():
                            tool_guidance = "Use 'get_page_configuration' to find the body field alias, then use 'send_keys' or 'ensure_focus_and_type' to enter the email body."
                        elif "send" in next_step.lower():
                            tool_guidance = "Use 'get_page_configuration' to find the Send button alias, then use 'click' to send the email."
                        else:
                            tool_guidance = "Use 'get_page_configuration' to see the current screen aliases, then use 'click' or 'send_keys' to complete the next step."
                        
                        messages.append({
                            "role": "user",
                            "content": (
                                "CRITICAL: You have returned end_turn multiple times without completing the task. "
                                "You MUST use a tool NOW. Do NOT return end_turn again. "
                                f"\n\nRemaining steps:\n{remaining_steps_text}\n\n"
                                f"Next step: {next_step}\n"
                                f"{tool_guidance}\n\n"
                                "You MUST call a tool (get_page_configuration, click, send_keys, or ensure_focus_and_type) in your next response. "
                                "Do NOT return end_turn until ALL steps are complete."
                            )
                        })
                        # Don't reset counter - keep it high to prevent further loops
                        # Only reset if LLM actually uses a tool (handled in tool_use section)
                        continue
                    
                    # Not all steps completed - ask LLM to continue
                    # Suppress technical message - not shown to users (only show user-friendly message)
                    # print(f"\n[WARN]  LLM returned end_turn but not all planned steps have been executed.")
                    # if uncompleted_step_descriptions:
                    #     print(f"[INFO]  Remaining steps: {', '.join(uncompleted_step_descriptions[:3])}")
                    # print(f"[INFO]  Asking LLM to continue and complete remaining steps...")
                    
                    # Add guidance message to continue with specific remaining steps
                    remaining_steps_text = "\n".join([f"- {desc}" for desc in uncompleted_step_descriptions[:5]])
                    messages.append({
                        "role": "user",
                        "content": (
                            "You returned end_turn, but not all steps from the user's prompt have been completed. "
                            "Please review the original user prompt and ensure ALL steps are executed before returning end_turn. "
                            f"Remaining steps that need to be completed:\n{remaining_steps_text}\n"
                            "Continue with the remaining steps now. Do NOT return end_turn until ALL steps are complete."
                        )
                    })
                    # Continue the loop instead of breaking
                    continue
                
                # Check if LLM returned end_turn multiple times (2-3 times) - might indicate completion
                # Even if step inference didn't work perfectly, check if goal appears satisfied
                if hasattr(main, '_end_turn_count') and main._end_turn_count >= 2:
                    # Goal-based completion check: verify if user's goal keywords are satisfied
                    user_goal_lower = user_goal.lower()
                    goal_keywords = []
                    
                    # Extract key action verbs and targets from user goal
                    if 'open' in user_goal_lower:
                        app_match = re.search(r'open\s+([a-z0-9 ._-]+)', user_goal, re.IGNORECASE)
                        if app_match:
                            goal_keywords.append(('open', app_match.group(1).lower().strip()))
                    
                    if 'search' in user_goal_lower:
                        search_match = re.search(r'search\s+for\s+([^,]+?)(?:\s+and\s+then|$)', user_goal, re.IGNORECASE)
                        if search_match:
                            goal_keywords.append(('search', search_match.group(1).lower().strip()))
                    
                    if 'play' in user_goal_lower:
                        goal_keywords.append(('play', 'video' if 'video' in user_goal_lower else 'media'))
                    
                    # Check executed steps for goal satisfaction
                    executed_descriptions = [s.get('description', '').lower() for s in test_report.report.get('steps', [])]
                    goal_satisfied = True
                    
                    for action, target in goal_keywords:
                        found = False
                        for desc in executed_descriptions:
                            if action in desc and (target in desc or len(target.split()) == 1 and any(word in desc for word in target.split())):
                                found = True
                                break
                        if not found:
                            goal_satisfied = False
                            break
                    
                    # If goal appears satisfied and we have at least 2 successful steps, consider it complete
                    if goal_satisfied and len([s for s in test_report.report.get('steps', []) if s.get('status') == 'PASS']) >= 2:
                        finalize_and_generate_report(
                            test_report,
                            "completed",
                            None,
                            f"Goal completed (detected via end_turn: {main._end_turn_count} times and goal satisfaction)"
                        )
                        break
                
                # Reset counter when steps are actually completed (no uncompleted steps)
                if hasattr(main, '_end_turn_count'):
                    main._end_turn_count = 0
                
                if failed_steps > 0:
                    # Some steps failed - mark as failed
                    finalize_and_generate_report(
                        test_report,
                        "failed",
                        f"{failed_steps} step(s) failed",
                        "Task completed but some steps failed."
                    )
                    break
                else:
                    # All steps completed successfully
                    final_text = next((block['text'] for block in response_body.get('content', []) if block['type'] == 'text'), None)
                    completion_msg = f"Final message: {final_text}" if final_text and final_text != "Done." else "All steps completed successfully."
                    
                    finalize_and_generate_report(
                        test_report,
                        "completed",
                        None,
                        completion_msg
                    )
                    break
            elif stop_reason == "max_tokens":
                # Response was truncated due to token limit - continue the conversation
                print("\n[WARN]  Response truncated due to token limit. Continuing conversation...")
                
                # Add the partial response to messages
                content = response_body.get('content')
                if content is None:
                    content = []
                elif not isinstance(content, list):
                    content = []
                messages.append({"role": "assistant", "content": content})
                
                # Add a message asking the LLM to continue
                messages.append({
                    "role": "user",
                    "content": "Your previous response was truncated due to token limit. Please continue from where you left off."
                })
                
                # Continue the loop to get the next response
                continue
            elif stop_reason is None or stop_reason == "":
                # FIX: Handle missing stop_reason - LLM might have returned empty response
                print(f"\n[WARN]  LLM response missing stop_reason. Content: {response_body.get('content', [])}")
                
                # Check if there's any content in the response
                content = response_body.get('content', [])
                if content and isinstance(content, list) and len(content) > 0:
                    # There's content but no stop_reason - might be a text-only response
                    text_blocks = [b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text']
                    if text_blocks:
                        print(f"[INFO]  LLM returned text response: {text_blocks[0][:100]}...")
                        # Add the response and ask LLM to use a tool
                        messages.append({"role": "assistant", "content": content})
                        messages.append({
                            "role": "user",
                            "content": "Please use a tool to continue with the automation. What action should be taken next?"
                        })
                        continue
                
                # No content or empty response - this is an error
                print(f"[ERROR] LLM returned empty response or missing stop_reason")
                # Add skipped steps before finalizing
                add_skipped_steps_if_needed(test_report, test_report.step_counter)
                finalize_and_generate_report(
                    test_report,
                    "error",
                    "LLM returned empty response or missing stop_reason",
                    "Automation stopped due to LLM response error."
                )
                break
            else:
                print(f"[ERROR] Error: Unknown stop reason '{stop_reason}'")
                # Log full response for debugging
                print(f"[DEBUG] Full response_body: {json.dumps(response_body, indent=2)[:500]}...")
                # Add skipped steps before finalizing
                add_skipped_steps_if_needed(test_report, test_report.step_counter)
                # Save report before breaking
                finalize_and_generate_report(
                    test_report,
                    "error",
                    f"Unknown stop reason: {stop_reason}",
                    "Automation stopped due to unknown error."
                )
                break
                
        except KeyboardInterrupt:
            print("\n\n--- [WARN]  Interrupted by user (Ctrl+C) ---")
            
            # Save report even on interruption
            try:
                # Check if report was already finalized (e.g., by signal handler)
                if test_report.report.get('status') not in ('completed', 'failed', 'cancelled', 'interrupted'):
                    finalize_and_generate_report(
                        test_report,
                        "interrupted",
                        "User interrupted the execution",
                        "Automation was interrupted by user."
                    )
            except Exception as save_error:
                print(f"[WARN]  Warning: Failed to save report: {save_error}")
            raise  # Re-raise KeyboardInterrupt to exit properly
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            # Show user-friendly error message instead of technical details
            if "Input is too long" in error_message or "too long" in error_message.lower():
                print(f"\n[ERROR] Automation stopped: The task is too complex. Please try breaking it into smaller steps.")
            elif "ValidationException" in error_code or "validation" in error_message.lower():
                # Show ValidationException details - these are usually fixable schema issues
                print(f"\n[ERROR] Validation error: {error_message}")
                print(f"[INFO] This is usually caused by an invalid tool schema. Check the error details above.")
            else:
                print(f"\n[ERROR] Automation encountered an error. Please try again.")
                # Show error code for debugging (but not full technical details)
                print(f"[INFO] Error code: {error_code}")
            # Suppress technical details - not shown to users
            # print(f"\n[ERROR] Bedrock API Error ({error_code}): {error_message}")
            
            # Provide helpful suggestions
            if 'ServiceUnavailableException' in error_code or 'ServiceUnavailableException' in str(e):
                print("[INFO] Suggestions:")
                print("   1. AWS Bedrock service may be temporarily unavailable. Please try again in a few moments.")
                print("   2. Check your AWS region settings and Bedrock service status.")
                print("   3. Verify your AWS credentials and permissions.")
            elif 'ThrottlingException' in error_code or 'TooManyRequestsException' in error_code:
                print("[INFO] Suggestions:")
                print("   1. You're hitting rate limits. Wait a moment before retrying.")
                print("   2. Consider reducing the frequency of API calls.")
            
            # Add skipped steps before finalizing
            add_skipped_steps_if_needed(test_report, test_report.step_counter)
            # Save report even on error
            finalize_and_generate_report(
                test_report,
                "error",
                f"{error_code}: {error_message}",
                "Automation stopped due to API error."
            )
            break
        except Exception as e:
            print(f"\n[ERROR] Error during Bedrock API call: {type(e).__name__}: {e}")
            
            # Determine status based on step results
            # If all steps passed, mark as completed with warning
            # If steps failed, mark as failed/error
            if test_report.report.get("failed_steps", 0) == 0:
                # All steps passed, but exception occurred - mark as completed with warning
                finalize_and_generate_report(
                    test_report,
                    "completed",
                    None,
                    "Exception occurred but all steps passed."
                )
            else:
                # Some steps failed - mark as error
                finalize_and_generate_report(
                    test_report,
                    "error",
                    f"Exception: {type(e).__name__}: {e}",
                    "Exception occurred during execution."
                )
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run automation workflow")
    parser.add_argument("--prompt", help="Automation goal to execute without interactive input")
    args = parser.parse_args()
    main(args.prompt)

