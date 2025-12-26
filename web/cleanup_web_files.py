#!/usr/bin/env python3
"""
Script to clean up web-scraped text files by removing navigation elements,
tabs, and other artifacts while preserving useful content.
"""

import os
import re
from pathlib import Path

# Navigation and boilerplate patterns to remove (exact line matches)
REMOVE_LINES = {
    "Skip to main content",
    "Skip to internal navigation",
    "Request Account",
    "User Guide",
    "Contact Us",
    "Accounts & Allocations",
    "Resources",
    "Grants & Publications",
    "Support & Services",
    "About RCC",
    "Section Navigation",
    "navigateright",
    "Get an Account",
    "Get Support",
    "Primary tabs",
    "View",
    "(active tab)",
    "What links here",
    "previous",
    "next",
    # Common navigation items
    "Director's Welcome",
    "Our Team",
    "Vision & Mission",
    "News & Features",
    "Calendar",
    "Committees",
    "Location & Directions",
    "RCC User Policy",
    "Job Opportunities",
    # Support & Services section nav
    "Cluster Partnership Program",
    "Consultant Partnership Program",
    "New Faculty Program",
    "Workshops and Training",
    "Data Sharing Services",
    "Data Management",
    "Consulting and Technical Support",
    "Outreach",
    # Resources section nav
    "Storage and Backup",
    "Software",
    "Visualization",
    "Networking",
    "Hosted Data",
    "Secure Research Environment",
    "Cloud",
    "Quantum",
    "GIS",
    # Grants section nav
    "Acknowledging the RCC",
    "Facilities and Resources Documents",
    "For PI Proposals",
    "Grant Support",
    "Hardware Quotes",
    "List of Publications",
    "Publications",
    "Support Letters",
    # About section nav
    "Advisory Committees",
    "Research Computing Oversight Committee",
}

# Patterns that indicate a line is purely navigation (regex patterns)
NAV_PATTERNS = [
    r'^navigateright$',
    r'^\(active tab\)$',
    r'^View$',
    r'^next$',
    r'^previous$',
]


def clean_line(line: str) -> str:
    """Clean a single line by removing extra whitespace and tabs."""
    # Remove tabs and replace with single space
    line = line.replace('\t', ' ')
    # Collapse multiple spaces into one
    line = re.sub(r' +', ' ', line)
    # Strip leading/trailing whitespace
    return line.strip()


def is_navigation_line(line: str) -> bool:
    """Check if a line is purely navigation/boilerplate."""
    stripped = line.strip()
    
    # Check exact matches
    if stripped in REMOVE_LINES:
        return True
    
    # Check regex patterns
    for pattern in NAV_PATTERNS:
        if re.match(pattern, stripped):
            return True
    
    return False


def fix_line_wrapping(text: str) -> str:
    """Fix lines that were incorrectly wrapped mid-word or mid-sentence."""
    lines = text.split('\n')
    result = []
    i = 0
    
    while i < len(lines):
        current = lines[i].rstrip()
        
        # Skip empty lines
        if not current:
            result.append('')
            i += 1
            continue
        
        # Check if we should merge with next line
        while i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            
            # Don't merge if next line is empty
            if not next_line:
                break
            
            # Don't merge if current line ends with sentence-ending punctuation
            if current.rstrip().endswith(('.', '!', '?', ':', ';')):
                break
            
            # Don't merge if next line starts with bullet or special chars
            if next_line.startswith(('•', '-', '*', '–', 'http', 'https', 'URL:', 'Title:')):
                break
            
            # Don't merge separator lines
            if next_line.startswith('=' * 10):
                break
            
            # Merge if current line ends mid-word (ends with letter/number) 
            # and next starts with lowercase letter
            if (current and current[-1].isalnum() and next_line and next_line[0].islower()):
                current = current + next_line
                i += 1
                continue
            
            # Merge if current line ends with incomplete word (long line ending with letter)
            # This handles the column-width wrapping issue
            if len(current) >= 60 and current and current[-1].isalpha():
                # Check if next line looks like a continuation (starts with lowercase or continues a word)
                if next_line and (next_line[0].islower() or 
                                  (next_line[0].isupper() and not next_line.split()[0].istitle())):
                    current = current + next_line
                    i += 1
                    continue
            
            break
        
        result.append(current)
        i += 1
    
    return '\n'.join(result)


def clean_content(content: str) -> str:
    """Clean the entire content of a file."""
    lines = content.split('\n')
    cleaned_lines = []
    
    # Track state
    in_header = True  # Skip header section until we hit the separator
    found_separator = False
    
    for i, line in enumerate(lines):
        # Keep URL and Title lines
        if line.startswith('URL:') or line.startswith('Title:'):
            cleaned_lines.append(line)
            continue
        
        # Keep separator line
        if line.startswith('=' * 20):
            cleaned_lines.append(line)
            found_separator = True
            in_header = True  # Start skipping navigation after separator
            continue
        
        # Skip navigation section after separator
        if found_separator and in_header:
            stripped = line.strip()
            # Check if this looks like the start of real content
            # Real content usually starts with a longer sentence or paragraph
            if stripped and not is_navigation_line(stripped):
                # Check if it's a meaningful content line (longer than typical nav items)
                if len(stripped) > 50 or (
                    i + 1 < len(lines) and 
                    len(lines[i + 1].strip()) > 50 and 
                    not is_navigation_line(lines[i + 1].strip())
                ):
                    in_header = False
                    # Fall through to process this line
                else:
                    # Might still be navigation, check if it matches known nav
                    if is_navigation_line(stripped):
                        continue
                    # Short line that's not navigation - could be section header
                    # Check next few lines for content
                    has_content_ahead = False
                    for j in range(i + 1, min(i + 5, len(lines))):
                        future_line = lines[j].strip()
                        if len(future_line) > 60 and not is_navigation_line(future_line):
                            has_content_ahead = True
                            break
                    if has_content_ahead:
                        in_header = False
                    else:
                        continue
        
        if in_header and found_separator:
            continue
        
        # Skip pure navigation lines
        if is_navigation_line(line):
            continue
        
        # Clean and add the line
        cleaned = clean_line(line)
        
        # Skip empty lines at the beginning of content
        if not cleaned_lines or cleaned_lines[-1].startswith('='):
            if not cleaned:
                continue
        
        cleaned_lines.append(cleaned)
    
    # Join lines and clean up
    result = '\n'.join(cleaned_lines)
    
    # Fix line wrapping issues (lines broken mid-word or mid-sentence)
    result = fix_line_wrapping(result)
    
    # Remove excessive blank lines (more than 2 consecutive)
    result = re.sub(r'\n{3,}', '\n\n', result)
    
    # Remove trailing whitespace
    result = '\n'.join(line.rstrip() for line in result.split('\n'))
    
    return result.strip()


def process_file(filepath: Path) -> tuple[bool, str]:
    """Process a single file and return (success, message)."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        cleaned = clean_content(content)
        
        # Write back
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(cleaned)
        
        # Calculate reduction
        original_len = len(content)
        cleaned_len = len(cleaned)
        reduction = ((original_len - cleaned_len) / original_len) * 100 if original_len > 0 else 0
        
        return True, f"Cleaned {filepath.name}: {original_len} -> {cleaned_len} bytes ({reduction:.1f}% reduction)"
    
    except Exception as e:
        return False, f"Error processing {filepath.name}: {str(e)}"


def main():
    """Main function to process all txt files."""
    web_dir = Path('/project/rcc/youzhi/user-guide/web')
    
    if not web_dir.exists():
        print(f"Directory not found: {web_dir}")
        return
    
    txt_files = list(web_dir.glob('*.txt'))
    print(f"Found {len(txt_files)} text files to process\n")
    
    success_count = 0
    error_count = 0
    
    for filepath in sorted(txt_files):
        # Skip this script if it somehow has .txt extension
        if filepath.name == 'cleanup_web_files.py':
            continue
        
        success, message = process_file(filepath)
        print(message)
        
        if success:
            success_count += 1
        else:
            error_count += 1
    
    print(f"\n{'='*60}")
    print(f"Processed {success_count} files successfully, {error_count} errors")


if __name__ == '__main__':
    main()
