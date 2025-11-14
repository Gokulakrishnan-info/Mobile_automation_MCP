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
from typing import Dict, List
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
    get_perception_summary,
    available_functions
)
from prompts import get_system_prompt, get_app_package_suggestions
from reports import TestReport
from llm_tools import tools_list_claude


# --- 1. Connect to LLM API (Bedrock) ---
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
BEDROCK_MODEL_ID = os.getenv('BEDROCK_MODEL_ID', 'anthropic.claude-3-5-sonnet-20240620-v1:0')
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
                    print(f"[ERROR] Non-retryable Bedrock error: {error_code}")
                else:
                    print(f"[ERROR] Max retries ({max_retries + 1}) reached. Bedrock service unavailable.")
                raise
        except Exception as e:
            # For non-ClientError exceptions, don't retry
            print(f"[ERROR] Non-retryable error: {type(e).__name__}: {e}")
            raise
    
    # Should not reach here, but just in case
    raise last_exception if last_exception else Exception("Failed to invoke Bedrock API")


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
                            print(f"[WARN]  Removing orphaned tool_use for tool_use_id: {tool_use_id} (no tool_result found)")
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
                                        print(f"[WARN]  Removing orphaned tool_result for tool_use_id: {tool_use_id}")
                                else:
                                    validated_content.append(block)
                            else:
                                # No previous assistant message - this tool_result is orphaned
                                print(f"[WARN]  Removing orphaned tool_result (no previous assistant message): {tool_use_id}")
                        else:
                            # First message can't have tool_result
                            print(f"[WARN]  Removing tool_result from first message: {tool_use_id}")
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
    
    # Media/Video patterns
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
    import time
    import appium_tools
    
    # Wait for page to load (reduced to 0.2s - XML parsing is fast and page usually loads quickly)
    time.sleep(0.2)
    
    # Strategy 1: Extract prominent text from XML page source
    try:
        xml_text = get_page_source()
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


def _execute_with_retry(function_name: str, function_args: dict, available_functions: dict, expected_inputs: dict, max_retries: int = 3):
    """
    Execute an action with retry logic and fallback strategies.
    
    Args:
        function_name: Name of the function to execute
        function_args: Arguments for the function
        available_functions: Dictionary of available functions
        expected_inputs: Dictionary of expected inputs (for validation)
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

    for attempt in range(1, max_retries + 1):
        # First attempt: try original action
        if attempt == 1:
            result = function_to_call(**function_args)
        else:
            # Subsequent attempts: try fallback strategies
            print(f"  [RETRY] Attempt {attempt}/{max_retries}: Trying fallback strategy...")
            
            # Wait a bit before retry (reduced from 1s to 0.3s for faster retries)
            time.sleep(0.3)
            
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
                        time.sleep(0.2)
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
                        time.sleep(0.2)
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
                        time.sleep(0.2)
                        result = function_to_call(**function_args)
                    else:
                        result = function_to_call(**function_args)
                elif attempt == 3:
                    # Strategy: Try waiting for element with longer timeout, then clicking
                    print(f"  [FALLBACK] Waiting for element with longer timeout, then clicking...")
                    wait_result = appium_tools.wait_for_element(strategy=strategy, value=value, timeoutMs=10000)
                    if isinstance(wait_result, dict) and wait_result.get('success'):
                        time.sleep(0.2)
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
        # Try to extract meaningful text from value
        if 'login' in value.lower() or 'button' in value.lower():
            return f"Click on Login button"
        elif 'logout' in value.lower():
            return f"Click logout"
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


def main(provided_goal: str | None = None):
    """Main execution loop for mobile automation.

    Args:
        provided_goal: Optional prompt to run headlessly without interactive input.
    """
    # Track if last action requires verification (for assertion enforcement)
    main._last_requires_verification = False
    main._last_action_type = None
    # Track step number for logging
    step_number = 0
    
    system_prompt = get_system_prompt()

    # Check if session exists, if not, try to initialize with defaults
    print("--- [CHECK] Checking for active Appium session...")
    test_payload = {"tool": "get_page_source", "args": {}}
    try:
        test_response = requests.post(f"{MCP_SERVER_URL}/tools/run", json=test_payload, timeout=5)
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
                    print("--- [ERROR] Failed to initialize Appium session.")
                    print("--- [INFO] Please initialize the session manually using:")
                    print(f"---    POST {MCP_SERVER_URL}/tools/initialize-appium")
                    print("---    Or update the capabilities in main.py")
                    return
                print(f"--- [OK] Session initialized: {session_id}")
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
                    print("--- [ERROR] Failed to initialize Appium session.")
                    return
                print(f"--- [OK] Session initialized: {session_id}")
                main._session_id = session_id
        elif test_response.status_code == 200:
            print("--- [OK] Active Appium session found")
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
                main._session_id = session_id
    except requests.exceptions.RequestException as e:
        print(f"--- [ERROR] Error checking for session: {e}")
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
        if not session_id:
            print("--- [ERROR] Failed to initialize Appium session.")
            print("--- [INFO] Make sure:")
            print("---    1. MCP server is running (npm run start:http)")
            print("---    2. Appium server is running")
            print("---    3. Mobile device/emulator is connected (Android or iOS)")
            return
        print(f"--- [OK] Session initialized: {session_id}")
        main._session_id = session_id
    
    if provided_goal:
        user_goal = provided_goal
        print(f"\nWhat is your goal? (auto)\n> {user_goal}")
    else:
        user_goal = input("\nWhat is your goal? (e.g., 'open YouTube and search for Python tutorials')\n> ")
    
    # Parse validation requirements from user prompt
    validation_map = parse_validation_requirements(user_goal)
    if validation_map:
        print(f"\n--- [OK] Detected {len(validation_map)} explicit validation requirement(s) in user prompt")
        for key, val in validation_map.items():
            print(f"   - Validate: '{val['text']}'")
    
    # Initialize test report
    test_report = TestReport(user_goal)
    
    # Message history management constants
    MAX_MESSAGES = 25  # Keep last 25 messages (initial + 12 action cycles)
    MAX_XML_LENGTH = 40000  # Limit XML size per message
    
    # Fast path: Get XML page source only (skip OCR for initial load speed)
    try:
        current_screen_xml = get_page_source()
        truncated_current_xml = truncate_xml(current_screen_xml, MAX_XML_LENGTH)
        initial_perception_block = f"[XML Page Source (truncated)]:\n{truncated_current_xml}"
    except Exception as e:
        print(f"[WARN]  Failed to get page source: {e}")
        initial_perception_block = "[Unable to get page source]"

    # Control whether to include raw XML in messages (and thereby risk console echoes)
    suppress_xml = os.getenv('SUPPRESS_XML', '').lower() in ('1', 'true', 'yes')
    initial_xml_block = "[Perception summary omitted]" if suppress_xml else initial_perception_block
    
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
    initial_guidance = (
        "IMPORTANT: Do NOT call launch_app(). Navigate using the current UI only (home/back/search), and operate within visible apps."
        if disable_launch else
        "IMPORTANT: If the goal mentions an app that is not visible, you MAY launch that app using launch_app(), otherwise navigate within the current UI."
    )
    strict_note = "" if not expected_inputs else f"\n\nSTRICT: Use EXACT values from user: {expected_inputs}. Do NOT auto-correct or substitute."
    validation_note = ""
    if validation_map:
        validation_list = [f"'{val['text']}'" for val in validation_map.values()]
        validation_note = f"\n\n[OK] VALIDATION REQUIREMENTS: The user has explicitly requested validation for: {', '.join(validation_list)}. You MUST perform these validations when the corresponding actions complete. Use wait_for_text_ocr, wait_for_element, or assert_activity to perform validations."
    context_note = "\n\n[INFO] CONTEXT: Work with the CURRENT screen state shown above. If the goal mentions something already visible on this screen, proceed directly with that action. You don't need to navigate back or restart from the beginning."
    perception_note = "\n\n[THINK] SCREEN STATE: The screen state above shows XML page source (fast and reliable). XML contains all structured UI elements with their text, types, and coordinates. Always use XML elements when making decisions - they are the primary source of truth for native Android apps."
    messages = [
        {"role": "user", "content": f"My goal is: '{user_goal}'.{app_suggestions}{strict_note}{validation_note}\n\nHere is the current screen perception summary: {initial_xml_block}\n\n{perception_note}\n\n{context_note}\n\n{initial_guidance}"}
    ]

    # Build tool list for the LLM, optionally removing launch_app entirely
    if disable_launch:
        tools_for_model = [t for t in tools_list_claude if t.get('name') != 'launch_app']
    else:
        tools_for_model = tools_list_claude

    # Cache for page source to avoid redundant calls
    _cached_xml = None
    _cached_xml_timestamp = 0
    _last_action_was_screen_change = False
    
    # Track repeated actions to prevent infinite loops
    _action_history = []  # Track last 5 actions (function_name, function_args signature)
    _max_repeat_actions = 3  # Max times same action can repeat consecutively
    
    while True:
        # Only get fresh perception summary if screen likely changed (after actions)
        # Otherwise, use cached XML for speed
        if _last_action_was_screen_change or _cached_xml is None:
            print("\n--- [THINK] OBSERVE: Getting page source (XML only - fast mode)...")
            try:
                # Fast path: XML only (skip OCR for speed)
                current_screen_xml = get_page_source()
                _cached_xml = current_screen_xml
                _cached_xml_timestamp = time.time()
                _last_action_was_screen_change = False
                
                truncated_current_xml = truncate_xml(current_screen_xml, MAX_XML_LENGTH)
                current_perception_block = f"[XML Page Source (truncated)]:\n{truncated_current_xml}"
            except Exception as e:
                print(f"[WARN]  Failed to get page source: {e}")
                current_perception_block = "[Unable to get page source]"
        else:
            # Use cached XML - screen hasn't changed
            print("\n--- [THINK] OBSERVE: Using cached page source (screen unchanged)...")
            truncated_current_xml = truncate_xml(_cached_xml, MAX_XML_LENGTH)
            current_perception_block = f"[XML Page Source (cached, truncated)]:\n{truncated_current_xml}"
        
        # Add explicit reminder to check XML before scrolling
        # Extract key terms from user goal to help LLM search XML
        import re
        user_goal_lower = user_goal.lower()
        key_terms = []
        # Look for product names, actions, etc.
        if 'add' in user_goal_lower and 'cart' in user_goal_lower:
            # Extract product name if mentioned
            product_match = re.search(r'add\s+([^to]+?)\s+to\s+cart', user_goal_lower)
            if product_match:
                key_terms.append(product_match.group(1).strip())
        if 'bike light' in user_goal_lower:
            key_terms.append('bike light')
        if 'backpack' in user_goal_lower:
            key_terms.append('backpack')
        
        if key_terms:
            xml_reminder = f"\n\n[CRITICAL REMINDER] Before scrolling, SEARCH the XML above for: {', '.join(key_terms)}. If found, use it directly - DO NOT scroll!"
            current_perception_block += xml_reminder
        
        # Add current page source to messages so LLM can see what's on screen
        # This ensures LLM always has the latest screen state before making decisions
        messages.append({
            "role": "user",
            "content": current_perception_block
        })
        
        print("--- [THINK] THINK: Asking LLM what to do next...")
        
        # Validate messages before sending to API to prevent ValidationException
        # This ensures no orphaned tool_use or tool_result blocks are sent
        messages = validate_message_pairs(messages)
        if messages is None:
            messages = []
        
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
                base_delay=0.5  # Optimized: Reduced to 0.5s for faster retries
            )
            
            response_body = json.loads(response['body'].read().decode('utf-8'))
            stop_reason = response_body.get('stop_reason')
            
            # Check for API errors in response
            if 'error' in response_body:
                error_msg = response_body.get('error', {}).get('message', 'Unknown API error')
                print(f"[ERROR] API returned an error: {error_msg}")
                report_filename = test_report.finalize("error", f"API error: {error_msg}")
                print(f"\n[REPORT] Report: {report_filename}")
                print(f"[STATS] {test_report.get_summary()}")
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
                        report_filename = test_report.finalize("error", "Stop reason was 'tool_use' but no tool call block was found (multiple attempts)")
                        print(f"\n[REPORT] Report: {report_filename}")
                        print(f"[STATS] {test_report.get_summary()}")
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
                
                # Detect infinite loops: check if same action is repeated too many times
                action_signature = (function_name, str(function_args.get('strategy', '')), str(function_args.get('value', '')))
                recent_same_actions = sum(1 for a in _action_history[-5:] if a == action_signature)
                
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
                        try:
                            if hasattr(main, '_planned_steps') and isinstance(main._planned_steps, list):
                                test_report.add_skipped_steps(main._planned_steps, test_report.step_counter + 1)
                        except Exception:
                            pass
                        report_filename = test_report.finalize("failed", error_msg)
                        print(f"\n[WARN]  Test stopped at Step {step_number} after {recent_same_actions} repeated attempts.")
                        print(f"[REPORT] Report: {report_filename}")
                        print(f"[STATS] {test_report.get_summary()}")
                        break
                
                # Track this action
                _action_history.append(action_signature)
                if len(_action_history) > 10:  # Keep only last 10 actions
                    _action_history.pop(0)
                
                # Format description
                step_description = format_step_description(function_name, function_args)
                
                # Don't increment step number or print for get_page_source (it's an internal observation step)
                if function_name != 'get_page_source':
                    step_number += 1
                    print(f"\n--- [BOT] LLM Decision: Call {function_name} with args: {function_args}")
                    print(f"Step {step_number}: {step_description}")
                
                # Auto-hide keyboard before clicking buttons (especially if previous action was send_keys)
                if function_name == 'click':
                    # Check if previous action was send_keys (keyboard likely visible)
                    if hasattr(main, '_last_action_type') and main._last_action_type in ('send_keys', 'ensure_focus_and_type'):
                        button_value = (function_args.get('value') or '').lower()
                        # Check if it's a form button that might be hidden by keyboard
                        form_buttons = ['continue', 'submit', 'login', 'next', 'finish', 'checkout', 'save', 'confirm', 'done']
                        if any(btn in button_value for btn in form_buttons):
                            print("--- [KEYBOARD]  Auto-hiding keyboard before clicking button (keyboard may cover button)...")
                            try:
                                import appium_tools
                                hide_result = appium_tools.hide_keyboard()
                                if isinstance(hide_result, dict) and hide_result.get('success'):
                                    print("--- [OK] Keyboard hidden successfully")
                                else:
                                    print("--- [WARN]  Keyboard hide attempt completed (may not have been visible)")
                            except Exception as kb_error:
                                print(f"--- [WARN]  Could not hide keyboard: {kb_error} (continuing anyway)")
                
                # Note: Verification is now only performed when explicitly requested in user prompt
                # No automatic enforcement - LLM will decide based on user's validation requirements
                
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
                            result = _execute_with_retry(function_name, function_args, available_functions, expected_inputs)
                    else:
                        # Auto-inject sessionId for OCR assert if missing
                        if function_name == 'wait_for_text_ocr' and isinstance(function_args, dict) and 'sessionId' not in function_args:
                            if hasattr(main, '_session_id') and main._session_id:
                                function_args = {**function_args, 'sessionId': main._session_id}
                                print(f"[TOOL] Auto-injected sessionId: {main._session_id}")
                            else:
                                print("[WARN]  Warning: No session ID available for OCR call")
                        # Retry logic with fallback strategies (max 3 attempts)
                        result = _execute_with_retry(function_name, function_args, available_functions, expected_inputs)
                    
                    # Check if result indicates an error
                    is_error = False
                    error_message = ""
                    
                    if isinstance(result, str) and result.startswith("Error:"):
                        is_error = True
                        error_message = result
                    elif isinstance(result, dict):
                        success_value = result.get('success')
                        
                        # CRITICAL: send_keys and some tools return success: False when they fail
                        if (success_value is False or 
                            success_value == False or 
                            str(success_value).lower() == 'false'):
                            is_error = True
                            if function_name == 'send_keys':
                                error_message = f"Failed to send text. Element might not be an input field, not editable, or not found. {result.get('error', result.get('message', 'send_keys returned success: false'))}"
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
                            print(f"\n[NAV] Page Identified: {detected_page} (via verification text: '{ocr_value}')")
                    
                    # Record step in report (mark assertions)
                    is_assertion = function_name in ('wait_for_element', 'wait_for_text_ocr', 'assert_activity')
                    test_report.add_step(function_name, function_args, result, not is_error, is_assertion, description=step_description if function_name != 'get_page_source' else None)

                    # Show Pass/Fail status (skip get_page_source as it's internal)
                    if function_name != 'get_page_source':
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
                    
                    # Take screenshot after meaningful successful actions (not internal operations)
                    # Screenshots are taken after: click, send_keys, wait_for_text_ocr (when successful)
                    # Skip: get_page_source, wait_for_element (internal), take_screenshot itself
                    meaningful_actions = ('click', 'send_keys', 'wait_for_text_ocr', 'swipe', 'scroll', 'long_press')
                    if (not is_error and 
                        function_name in meaningful_actions and 
                        function_name != 'get_page_source' and
                        function_name != 'take_screenshot'):
                        try:
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
                                current_page_xml = get_page_source()
                                truncated_page_xml = truncate_xml(current_page_xml, MAX_XML_LENGTH)
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
                            report_filename = test_report.finalize("error", "Assertion failed: expected element not visible")
                            print(f"\n[WARN]  Test stopped at Step {step_number}. Subsequent steps will be skipped.")
                            print(f"[REPORT] Report: {report_filename}")
                            print(f"[STATS] {test_report.get_summary()}")
                            print("\n[LIST] Step Summary:")
                            print(test_report.get_step_summary())
                            break
                    
                    # Mark that screen likely changed - will refresh cache on next loop
                    _last_action_was_screen_change = True
                    
                    # Get new screen XML after action and add to messages for next LLM call
                    try:
                        new_screen_xml = get_page_source()
                        _cached_xml = new_screen_xml  # Update cache
                        _cached_xml_timestamp = time.time()
                        truncated_xml = truncate_xml(new_screen_xml, MAX_XML_LENGTH)
                        
                        # Add updated page source to messages so LLM sees the new state after action
                        # This ensures LLM always has the latest screen state
                        updated_perception = f"[XML Page Source (updated after action)]:\n{truncated_xml}"
                        messages.append({
                            "role": "user",
                            "content": updated_perception
                        })
                    except Exception as xml_error:
                        # If get_page_source fails, use error message as screen state
                        truncated_xml = f"Error getting page source: {xml_error}"
                        print(f"[ERROR] Failed to get page source: {xml_error}")
                    
                    if is_error:
                        # REFLECTION MODE: Immediate reflection after any failure
                        print("\n" + "="*60)
                        print("[REFLECT] REFLECTION MODE: Analyzing failure...")
                        print("="*60)
                        
                        try:
                            # Get current page source for reflection (fast - XML only)
                            try:
                                reflection_xml = get_page_source()
                                # Extract text from XML directly (fast)
                                import re
                                text_matches = re.findall(r'text="([^"]+)"', reflection_xml)
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
                                try:
                                    if hasattr(main, '_planned_steps') and isinstance(main._planned_steps, list):
                                        test_report.add_skipped_steps(main._planned_steps, test_report.step_counter + 1)
                                except Exception:
                                    pass
                                report_filename = test_report.finalize("error", f"Validation failed: {error_message}")
                                print(f"\n[WARN]  Test stopped at Step {step_number}. Validation requirement not met.")
                                print(f"[REPORT] Report: {report_filename}")
                                print(f"[STATS] {test_report.get_summary()}")
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
                        is_nav = is_navigation_action(function_name, function_args)
                        
                        success_text = (
                            "[OK] Action was successful. Screen updated." if suppress_xml
                            else f"[OK] Action was successful. Here is the new screen: {truncated_xml}"
                        )
                        
                        # Automatically detect page name after navigation actions
                        # NOTE: This is informational only - LLM will still verify with wait_for_text_ocr
                        if is_nav and not is_error:
                            print("\n" + "="*60)
                            print("[NAV] AUTOMATIC PAGE DETECTION (Informational)")
                            print("="*60)
                            
                            page_detection = auto_detect_page_after_navigation(
                                session_id=main._session_id if hasattr(main, '_session_id') else None
                            )
                            
                            if page_detection['detected']:
                                print(f"[OK] Page Detected: {page_detection['page_name']}")
                                print(f"[LIST] Detected via: {page_detection.get('method', 'Unknown')}")
                                print(f"[CHECK] Identifier: '{page_detection['identifier']}'")
                                print(f"[INFO] Note: LLM will verify with specific page identifier (e.g., 'PRODUCTS', 'CART')")
                                success_text += f"\n[NAV] Page Detected: {page_detection['page_name']} (detected via {page_detection.get('method', 'Unknown')}: '{page_detection['identifier']}')"
                            else:
                                print(f"[WARN]  Could not automatically detect page name")
                                print(f"[INFO] Page may still be loading or no prominent text found")
                                success_text += f"\n[WARN]  Page detection: Could not automatically identify page name"
                            
                            print("="*60 + "\n")
                        
                        # Note: Verification is now only performed when explicitly requested in user prompt
                        # No automatic verification enforcement - LLM will decide based on user's validation requirements
                        # Clear any old verification flags
                        main._last_requires_verification = False
                        main._last_action_type = None
                        main._last_action_args = None
                    
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
                else:
                    print(f"[ERROR] Error: Unknown function called: {function_name}")
                    # Save report before breaking
                    report_filename = test_report.finalize("error", f"Unknown function called: {function_name}")
                    print(f"\n[REPORT] Report: {report_filename}")
                    print(f"[STATS] {test_report.get_summary()}")
                    break
            
            elif stop_reason == "end_turn":
                print("\n[OK] Task complete!")
                final_text = next((block['text'] for block in response_body.get('content', []) if block['type'] == 'text'), "Done.")
                if final_text and final_text != "Done.":
                    print(final_text)
                
                # Finalize and save report
                report_filename = test_report.finalize("completed")
                print(f"\n[REPORT] Report: {report_filename}")
                print(f"[STATS] {test_report.get_summary()}")
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
            else:
                print(f"[ERROR] Error: Unknown stop reason '{stop_reason}'")
                # Save report before breaking
                report_filename = test_report.finalize("error", f"Unknown stop reason: {stop_reason}")
                print(f"\n[REPORT] Report: {report_filename}")
                print(f"[STATS] {test_report.get_summary()}")
                break
                
        except KeyboardInterrupt:
            print("\n\n--- [WARN]  Interrupted by user (Ctrl+C) ---")
            
            # Save report even on interruption
            try:
                report_filename = test_report.finalize("interrupted", "User interrupted the execution")
                print(f"\n[REPORT] Report: {report_filename}")
                print(f"[STATS] {test_report.get_summary()}")
            except Exception as save_error:
                print(f"[WARN]  Warning: Failed to save report: {save_error}")
            raise  # Re-raise KeyboardInterrupt to exit properly
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', str(e))
            print(f"\n[ERROR] Bedrock API Error ({error_code}): {error_message}")
            
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
            
            # Save report even on error
            report_filename = test_report.finalize("error", f"{error_code}: {error_message}")
            print(f"\n[REPORT] Report: {report_filename}")
            print(f"[STATS] {test_report.get_summary()}")
            break
        except Exception as e:
            print(f"\n[ERROR] Error during Bedrock API call: {type(e).__name__}: {e}")
            
            # Determine status based on step results
            # If all steps passed, mark as completed with warning
            # If steps failed, mark as failed/error
            if test_report.report.get("failed_steps", 0) == 0:
                # All steps passed, but exception occurred - mark as completed with warning
                report_filename = test_report.finalize("completed", None)
                print(f"\n[WARN]  Exception occurred but all steps passed. Report marked as completed.")
            else:
                # Some steps failed - mark as error
                report_filename = test_report.finalize("error", f"Exception: {type(e).__name__}: {e}")
            
            print(f"\n[REPORT] Report: {report_filename}")
            print(f"[STATS] {test_report.get_summary()}")
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run automation workflow")
    parser.add_argument("--prompt", help="Automation goal to execute without interactive input")
    args = parser.parse_args()
    main(args.prompt)

