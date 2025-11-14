"""
Test Report Management Module

Handles creation, tracking, and saving of test execution reports in JSON format.
"""
import json
from datetime import datetime
import os
from pathlib import Path
from typing import Dict, Any, Optional


class TestReport:
    """Manages test execution reports."""
    
    def __init__(self, user_prompt: str, reports_dir: str = "reports"):
        """Initialize a new test report.
        
        Args:
            user_prompt: The user's goal/command
            reports_dir: Directory to save reports (default: reports)
        """
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        
        self.report: Dict[str, Any] = {
            "user_prompt": user_prompt,
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "steps": [],
            "total_steps": 0,
            "successful_steps": 0,
            "failed_steps": 0,
            "skipped_steps": 0,
            "status": "in_progress",
            "reflections": []  # Store reflection analyses
        }
        
        self.step_counter = 0
        self.session_report_filename: Optional[Path] = None
    
    def add_reflection(self, step_number: int, reflection_text: str):
        """Add a reflection analysis for a failed step.
        
        Args:
            step_number: The step number that failed
            reflection_text: Claude's reflection analysis
        """
        self.report["reflections"].append({
            "step": step_number,
            "timestamp": datetime.now().isoformat(),
            "reflection": reflection_text
        })
    
    def add_step(self, action_name: str, args: Dict[str, Any], result: Any, success: bool, is_assertion: bool = False, description: Optional[str] = None):
        """Add a step to the report.
        
        Args:
            action_name: Name of the action/tool called
            args: Arguments passed to the action
            result: Result returned from the action
            success: Whether the action was successful
        """
        self.step_counter += 1

        # Sanitize result to avoid dumping large XML into reports
        suppress_xml = os.getenv('SUPPRESS_XML', '').lower() in ('1', 'true', 'yes')

        def _sanitize(value: Any) -> Any:
            try:
                if isinstance(value, str):
                    # Heuristic: page source XML
                    if suppress_xml and ('<hierarchy' in value or value.strip().startswith('<')):
                        return '[XML omitted]'
                    # Truncate extremely long strings to keep logs light
                    if len(value) > 4000:
                        return value[:2000] + '\n... [truncated] ...\n' + value[-500:]
                if isinstance(value, dict):
                    new_val = dict(value)
                    for k in ('xml', 'value', 'pageSource'):
                        if k in new_val and isinstance(new_val[k], str):
                            new_val[k] = _sanitize(new_val[k])
                    return new_val
                return value
            except Exception:
                return value

        sanitized_result = _sanitize(result)
        
        step_info = {
            "step": self.step_counter,
            "timestamp": datetime.now().isoformat(),
            "action": action_name,
            "description": description,
            "arguments": args,
            "success": success,
            "status": "PASS" if success else "FAIL",
            "result": str(sanitized_result) if not isinstance(sanitized_result, (dict, str)) else sanitized_result,
            "error": None,
            "is_assertion": is_assertion,
            # Enhanced fields for hybrid visual-AI flow
            "before_screenshot_path": None,
            "after_screenshot_path": None,
            "ocr_text_before": None,
            "ocr_text_after": None,
            "diff_score": None,
            "claude_reasoning": None,
            "recovery_attempts": None
        }
        
        # Extract enhanced data from result if available
        if isinstance(result, dict):
            if 'before_screenshot_path' in result:
                step_info["before_screenshot_path"] = result['before_screenshot_path']
            if 'after_screenshot_path' in result:
                step_info["after_screenshot_path"] = result['after_screenshot_path']
            if 'ocr_text_before' in result:
                step_info["ocr_text_before"] = result['ocr_text_before']
            if 'ocr_text_after' in result:
                step_info["ocr_text_after"] = result['ocr_text_after']
            if 'diff_score' in result:
                step_info["diff_score"] = result['diff_score']
            if 'claude_reasoning' in result:
                step_info["claude_reasoning"] = result['claude_reasoning']
            if 'recovery_attempts' in result:
                step_info["recovery_attempts"] = result['recovery_attempts']
        
        if not success:
            step_info["error"] = str(result.get('error', result.get('message', result))) if isinstance(result, dict) else str(result)
            self.report["failed_steps"] += 1
        else:
            self.report["successful_steps"] += 1
        
        self.report["steps"].append(step_info)
        self.report["total_steps"] = self.step_counter
        
        # Save report after each step (for real-time updates)
        self.save()
    
    def save(self) -> Path:
        """Save the report to a JSON file.
        
        Returns:
            Path to the saved report file
        """
        if self.session_report_filename is None:
            # Create new report file at start of session
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.session_report_filename = self.reports_dir / f"test_report_{timestamp}.json"
        
        # Update the same file throughout the session
        with open(self.session_report_filename, 'w', encoding='utf-8') as f:
            json.dump(self.report, f, indent=2, ensure_ascii=False)
        
        return self.session_report_filename
    
    def finalize(self, status: str = "completed", error: Optional[str] = None) -> Path:
        """Finalize the report and save it.
        
        Args:
            status: Final status ("completed", "error", etc.)
            error: Optional error message if status is "error"
            
        Returns:
            Path to the saved report file
        """
        self.report["end_time"] = datetime.now().isoformat()
        
        # Determine status based on step results
        # If all steps passed, always mark as completed (even if error occurred)
        failed_steps = self.report.get("failed_steps", 0)
        if failed_steps == 0:
            # All steps passed - mark as completed regardless of status parameter
            status = "completed"
        elif failed_steps > 0:
            # Some steps failed - mark as failed/error
            if status not in ("error", "failed"):
                status = "failed"
        
        self.report["status"] = status
        
        # Only set error if there's an actual error and status is error/failed
        if error and status in ("error", "failed"):
            self.report["error"] = error
            # Indicate that subsequent steps (if any) were skipped due to failure
            self.report["skipped_after_failure"] = True
            self.report["skipped_note"] = "Subsequent steps were skipped due to failure."
        elif error and status == "completed":
            # If error occurred but all steps passed, it might be a non-critical error
            # Store it as a warning instead
            self.report["warning"] = error
        
        return self.save()

    def add_skipped_steps(self, planned_steps: Any, start_from_step_index: int) -> None:
        """Append planned steps as SKIPPED from the given step index (1-based).
        planned_steps: list of dicts with 'step' and 'name' and optional 'description'.
        start_from_step_index: the next step number to mark as skipped (1-based).
        """
        try:
            if not isinstance(planned_steps, list):
                planned_steps = []
            appended_any = False
            for plan in planned_steps:
                try:
                    plan_step = int(plan.get('step', 0))
                except Exception:
                    plan_step = 0
                if plan_step >= start_from_step_index:
                    self.step_counter += 1
                    # Extract meaningful description from planned step
                    step_name = plan.get('name', '')
                    step_desc = plan.get('description', '')
                    
                    # Create meaningful description for skipped step based on user's original prompt
                    # Use the step name/description directly from the planned steps (which comes from user prompt)
                    if step_desc:
                        # Use description if available (most accurate to user's intent)
                        description = step_desc
                    elif step_name:
                        # Use step name, but make it more readable
                        description = step_name
                        # Clean up common patterns
                        if description.lower().startswith('click'):
                            description = description.replace('Click ', '').replace('click ', '').strip()
                            if description:
                                description = f"Click on {description}"
                        elif description.lower().startswith('type') or description.lower().startswith('enter'):
                            # Keep the full description for typing actions
                            pass
                        elif description.lower().startswith('add'):
                            # Keep the full description for add to cart actions
                            pass
                        elif description.lower().startswith('go to') or description.lower().startswith('navigate'):
                            # Keep navigation descriptions
                            pass
                        elif description.lower().startswith('fill') or description.lower().startswith('proceed'):
                            # Keep form filling descriptions
                            pass
                    else:
                        description = f"Planned step {plan_step} (from user prompt)"
                    
                    step_info = {
                        "step": self.step_counter,
                        "timestamp": datetime.now().isoformat(),
                        "action": "SKIPPED",
                        "description": description,
                        "arguments": {},
                        "success": False,
                        "status": "SKIPPED",
                        "error": "Skipped due to previous failure",
                        "is_assertion": False
                    }
                    self.report["steps"].append(step_info)
                    self.report["skipped_steps"] += 1
                    self.report["total_steps"] = self.step_counter
                    appended_any = True

            if not appended_any:
                self.step_counter += 1
                step_info = {
                    "step": self.step_counter,
                    "timestamp": datetime.now().isoformat(),
                    "action": "SKIPPED",
                    "description": "Remaining steps skipped due to previous failure.",
                    "arguments": {},
                    "success": False,
                    "status": "SKIPPED",
                    "error": "Skipped due to previous failure",
                    "is_assertion": False
                }
                self.report["steps"].append(step_info)
                self.report["skipped_steps"] += 1
                self.report["total_steps"] = self.step_counter
            self.save()
        except Exception:
            # Do not block on reporting errors
            pass
    
    def get_summary(self) -> str:
        """Get a summary string of the report.
        
        Returns:
            Summary string with step counts
        """
        return f"{self.report['total_steps']} steps | ✅ {self.report['successful_steps']} successful | ❌ {self.report['failed_steps']} failed | ⏭️ {self.report['skipped_steps']} skipped"
    
    def get_step_summary(self) -> str:
        """Get a formatted summary of all steps.
        
        Returns:
            Formatted string with step details
        """
        lines = []
        for step in self.report.get('steps', []):
            step_num = step.get('step', 0)
            action = step.get('action', 'Unknown')
            status = step.get('status', 'UNKNOWN')
            description = step.get('description', '')
            
            status_icon = '✅' if status == 'PASS' else '❌' if status == 'FAIL' else '⏭️'
            desc = description if description else action
            
            lines.append(f"  {status_icon} Step {step_num}: {desc} ({status})")
        
        return '\n'.join(lines) if lines else "No steps recorded."

