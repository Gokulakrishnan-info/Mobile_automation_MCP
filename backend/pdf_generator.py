"""
PDF Report Generator Module

Converts JSON test reports into well-formatted PDF documents.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


class PDFReportGenerator:
    """Generates PDF reports from JSON test reports."""
    
    def __init__(self, reports_dir: str = "reports"):
        """Initialize the PDF generator.
        
        Args:
            reports_dir: Directory where reports are stored
        """
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        
        if not REPORTLAB_AVAILABLE:
            raise ImportError(
                "reportlab is not installed. Install it with: pip install reportlab"
            )
    
    def generate_pdf(self, json_report_path: Path) -> Optional[Path]:
        """Generate a PDF report from a JSON report file.
        
        Args:
            json_report_path: Path to the JSON report file
            
        Returns:
            Path to the generated PDF file, or None if generation failed
        """
        try:
            # Load JSON report
            with open(json_report_path, 'r', encoding='utf-8') as f:
                report_data = json.load(f)
            
            # Generate PDF path
            pdf_path = json_report_path.with_suffix('.pdf')
            
            # Create PDF document
            doc = SimpleDocTemplate(
                str(pdf_path),
                pagesize=letter,
                rightMargin=0.75*inch,
                leftMargin=0.75*inch,
                topMargin=0.75*inch,
                bottomMargin=0.75*inch
            )
            
            # Container for PDF elements
            story = []
            
            # Get styles
            styles = getSampleStyleSheet()
            
            # Custom styles
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=24,
                textColor=colors.HexColor('#1a1a1a'),
                spaceAfter=30,
                alignment=1  # Center alignment
            )
            
            heading_style = ParagraphStyle(
                'CustomHeading',
                parent=styles['Heading2'],
                fontSize=16,
                textColor=colors.HexColor('#2c3e50'),
                spaceAfter=12,
                spaceBefore=20
            )
            
            # Title
            title = Paragraph("Automation Test Report", title_style)
            story.append(title)
            story.append(Spacer(1, 0.2*inch))
            
            # Create a style for the user prompt that allows wrapping
            prompt_style = ParagraphStyle(
                'PromptStyle',
                parent=styles['Normal'],
                fontSize=10,
                leading=14,
                spaceAfter=0,
                spaceBefore=0,
                leftIndent=0,
                rightIndent=0,
                wordWrap='LTR',
            )
            
            # Metadata table - use Paragraph for user prompt to enable wrapping
            user_prompt = report_data.get('user_prompt', 'N/A')
            user_prompt_para = Paragraph(self._escape_html(user_prompt), prompt_style)
            
            metadata_data = [
                ['User Prompt:', user_prompt_para],
                ['Start Time:', self._format_datetime(report_data.get('start_time'))],
                ['End Time:', self._format_datetime(report_data.get('end_time'))],
                ['Status:', self._format_status(report_data.get('status', 'unknown'))],
            ]
            
            metadata_table = Table(metadata_data, colWidths=[2*inch, 5*inch])
            metadata_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#ecf0f1')),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('ALIGN', (1, 0), (1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTNAME', (1, 0), (1, 0), 'Helvetica'),  # User prompt row
                ('FONTNAME', (1, 1), (1, -1), 'Helvetica'),  # Other rows
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#bdc3c7')),
            ]))
            story.append(metadata_table)
            story.append(Spacer(1, 0.3*inch))
            
            # Summary section
            summary_heading = Paragraph("Summary", heading_style)
            story.append(summary_heading)
            
            summary_data = [
                ['Total Steps', str(report_data.get('total_steps', 0))],
                ['Successful Steps', str(report_data.get('successful_steps', 0))],
                ['Failed Steps', str(report_data.get('failed_steps', 0))],
                ['Skipped Steps', str(report_data.get('skipped_steps', 0))],
            ]
            
            summary_table = Table(summary_data, colWidths=[3.5*inch, 3.5*inch])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#3498db')),
                ('BACKGROUND', (1, 0), (1, -1), colors.HexColor('#ecf0f1')),
                ('TEXTCOLOR', (0, 0), (0, -1), colors.whitesmoke),
                ('TEXTCOLOR', (1, 0), (1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTNAME', (1, 0), (1, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 11),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                ('TOPPADDING', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#34495e')),
            ]))
            story.append(summary_table)
            story.append(Spacer(1, 0.3*inch))
            
            # Error message if present (only show if status is error/failed)
            error_msg = report_data.get('error')
            warning_msg = report_data.get('warning')
            status = report_data.get('status', 'unknown')
            
            if error_msg and status in ('error', 'failed'):
                error_heading = Paragraph("Error Details", heading_style)
                story.append(error_heading)
                error_text = Paragraph(
                    self._escape_html(str(error_msg)),
                    styles['Normal']
                )
                error_box = Table(
                    [[error_text]],
                    colWidths=[7*inch],
                    style=TableStyle([
                        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fee')),
                        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#c00')),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('FONTNAME', (0, 0), (-1, -1), 'Courier'),
                        ('FONTSIZE', (0, 0), (-1, -1), 9),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                        ('TOPPADDING', (0, 0), (-1, -1), 10),
                        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#fcc')),
                    ])
                )
                story.append(error_box)
                story.append(Spacer(1, 0.3*inch))
            elif warning_msg:
                # Show warning for non-critical errors
                warning_heading = Paragraph("Warning", heading_style)
                story.append(warning_heading)
                warning_text = Paragraph(
                    self._escape_html(str(warning_msg)),
                    styles['Normal']
                )
                warning_box = Table(
                    [[warning_text]],
                    colWidths=[7*inch],
                    style=TableStyle([
                        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fff9e6')),
                        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#856404')),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('FONTNAME', (0, 0), (-1, -1), 'Courier'),
                        ('FONTSIZE', (0, 0), (-1, -1), 9),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                        ('TOPPADDING', (0, 0), (-1, -1), 10),
                        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#ffd700')),
                    ])
                )
                story.append(warning_box)
                story.append(Spacer(1, 0.3*inch))
            
            # Skipped Steps Summary (if any)
            skipped_steps_count = report_data.get('skipped_steps', 0)
            if skipped_steps_count > 0:
                skipped_heading = Paragraph("Skipped Steps Summary", heading_style)
                story.append(skipped_heading)
                
                steps = report_data.get('steps', [])
                skipped_steps = [s for s in steps if s.get('status') == 'SKIPPED']
                
                if skipped_steps:
                    skipped_list = []
                    for skipped in skipped_steps:
                        step_num = skipped.get('step', 0)
                        description = skipped.get('description', 'Unknown step')
                        skipped_list.append([f"Step {step_num}", self._escape_html(str(description))])
                    
                    skipped_table = Table(skipped_list, colWidths=[1.5*inch, 5.5*inch])
                    skipped_table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fff9e6')),
                        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#856404')),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
                        ('FONTSIZE', (0, 0), (-1, -1), 9),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                        ('TOPPADDING', (0, 0), (-1, -1), 6),
                        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#ffd700')),
                    ]))
                    story.append(skipped_table)
                    story.append(Spacer(1, 0.3*inch))
            
            # Steps section
            steps_heading = Paragraph("Test Steps", heading_style)
            story.append(steps_heading)
            
            steps = report_data.get('steps', [])
            if steps:
                for step in steps:
                    step_num = step.get('step', 0)
                    action = step.get('action', 'Unknown')
                    status = step.get('status', 'UNKNOWN')
                    description = step.get('description') or action
                    timestamp = self._format_datetime(step.get('timestamp'))
                    error = step.get('error')
                    arguments = step.get('arguments', {})
                    
                    # Step header
                    step_header = f"Step {step_num}: {description}"
                    step_para = Paragraph(
                        f"<b>{self._escape_html(step_header)}</b>",
                        styles['Heading3']
                    )
                    story.append(step_para)
                    
                    # Format status as simple text: Pass, Fail, or Skipped
                    status_text = self._format_status_simple(status)
                    
                    # Step details table
                    step_details = [
                        ['Action:', action],
                        ['Status:', status_text],
                        ['Timestamp:', timestamp],
                    ]
                    
                    # For send_keys and ensure_focus_and_type actions, show the text value that was sent
                    if action in ('send_keys', 'ensure_focus_and_type') and isinstance(arguments, dict):
                        sent_text = arguments.get('text', '')
                        if sent_text:
                            step_details.append(['Sent Value:', self._escape_html(str(sent_text))])
                    
                    if error:
                        step_details.append(['Error:', self._escape_html(str(error))])
                    
                    # Different styling for skipped steps
                    if status == 'SKIPPED':
                        # Highlight skipped steps with orange/yellow background
                        step_table = Table(step_details, colWidths=[1.5*inch, 5.5*inch])
                        step_table.setStyle(TableStyle([
                            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#fff9e6')),
                            ('BACKGROUND', (1, 0), (1, -1), colors.HexColor('#fff9e6')),
                            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#856404')),
                            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
                            ('FONTSIZE', (0, 0), (-1, -1), 9),
                            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                            ('TOPPADDING', (0, 0), (-1, -1), 6),
                            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#ffd700')),
                        ]))
                    else:
                        # Normal styling for passed/failed steps
                        step_table = Table(step_details, colWidths=[1.5*inch, 5.5*inch])
                        step_table.setStyle(TableStyle([
                            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f8f9fa')),
                            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
                            ('FONTSIZE', (0, 0), (-1, -1), 9),
                            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                            ('TOPPADDING', (0, 0), (-1, -1), 6),
                            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
                        ]))
                    story.append(step_table)
                    story.append(Spacer(1, 0.15*inch))
            else:
                no_steps = Paragraph("No steps recorded.", styles['Normal'])
                story.append(no_steps)
                story.append(Spacer(1, 0.2*inch))
            
            # Reflections section
            reflections = report_data.get('reflections', [])
            if reflections:
                story.append(PageBreak())
                reflections_heading = Paragraph("Reflections & Analysis", heading_style)
                story.append(reflections_heading)
                
                for reflection in reflections:
                    step_num = reflection.get('step', 0)
                    reflection_text = reflection.get('reflection', '')
                    reflection_time = self._format_datetime(reflection.get('timestamp'))
                    
                    reflection_header = Paragraph(
                        f"<b>Reflection for Step {step_num}</b> ({reflection_time})",
                        styles['Heading3']
                    )
                    story.append(reflection_header)
                    
                    reflection_para = Paragraph(
                        self._escape_html(reflection_text),
                        styles['Normal']
                    )
                    reflection_box = Table(
                        [[reflection_para]],
                        colWidths=[7*inch],
                        style=TableStyle([
                            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fff9e6')),
                            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                            ('FONTSIZE', (0, 0), (-1, -1), 9),
                            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
                            ('TOPPADDING', (0, 0), (-1, -1), 10),
                            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#ffd700')),
                        ])
                    )
                    story.append(reflection_box)
                    story.append(Spacer(1, 0.2*inch))
            
            # Build PDF
            doc.build(story)
            
            return pdf_path
            
        except Exception as e:
            print(f"Error generating PDF: {e}")
            return None
    
    def _format_datetime(self, dt_string: Optional[str]) -> str:
        """Format datetime string for display."""
        if not dt_string:
            return 'N/A'
        try:
            dt = datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            return dt_string
    
    def _format_status(self, status: str) -> str:
        """Format status string."""
        status_map = {
            'completed': 'Completed',
            'error': 'Error',
            'failed': 'Failed',
            'in_progress': 'In Progress',
            'success': 'Success',
        }
        return status_map.get(status.lower(), status.title())
    
    def _format_status_simple(self, status: str) -> str:
        """Format status as simple text: Pass, Fail, or Skipped."""
        status_upper = status.upper()
        if status_upper in ('PASS', 'SUCCESS', 'COMPLETED'):
            return 'Pass'
        elif status_upper in ('FAIL', 'ERROR', 'FAILED'):
            return 'Fail'
        elif status_upper == 'SKIPPED':
            return 'Skipped'
        else:
            return status
    
    def _get_status_color(self, status: str) -> str:
        """Get color for status."""
        color_map = {
            'PASS': '#27ae60',
            'FAIL': '#e74c3c',
            'SKIPPED': '#f39c12',
            'SUCCESS': '#27ae60',
        }
        return color_map.get(status.upper(), '#7f8c8d')
    
    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        if not isinstance(text, str):
            text = str(text)
        return (text
                .replace('&', '&amp;')
                .replace('<', '&lt;')
                .replace('>', '&gt;')
                .replace('"', '&quot;')
                .replace("'", '&#39;'))

