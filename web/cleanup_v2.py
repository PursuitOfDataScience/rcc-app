#!/usr/bin/env python3
"""
Script to clean up web-scraped text files by:
1. Removing navigation elements and boilerplate
2. Fixing line wrapping artifacts (lines broken mid-word/sentence)
3. Normalizing Unicode characters (smart quotes, em dashes, etc.)
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


def normalize_unicode(text: str) -> str:
    """Normalize Unicode characters to ASCII equivalents."""
    replacements = {
        '\u2019': "'",      # Right single quotation mark
        '\u2018': "'",      # Left single quotation mark
        '\u201c': '"',      # Left double quotation mark
        '\u201d': '"',      # Right double quotation mark
        '\u2013': '-',      # En dash
        '\u2014': '--',     # Em dash
        '\u2026': '...',    # Ellipsis
        '\u00a0': ' ',      # Non-breaking space
        '\u2022': '*',      # Bullet
        '\u00b7': '*',      # Middle dot
        '\u2212': '-',      # Minus sign
        '\u00d7': 'x',      # Multiplication sign
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def clean_line(line: str) -> str:
    """Clean a single line by removing extra whitespace and tabs."""
    # Replace tabs with space
    line = line.replace('\t', ' ')
    # Collapse multiple spaces into one
    line = re.sub(r' +', ' ', line)
    # Strip leading/trailing whitespace
    return line.strip()


def is_navigation_line(line: str) -> bool:
    """Check if a line is purely navigation/boilerplate."""
    stripped = line.strip()
    return stripped in REMOVE_LINES


def looks_like_continuation(current: str, next_line: str) -> bool:
    """Check if next_line looks like a continuation of current."""
    if not current or not next_line:
        return False
    
    current = current.rstrip()
    next_stripped = next_line.strip()
    
    # Don't continue if next line is empty
    if not next_stripped:
        return False
    
    # Don't continue if current ends with terminal punctuation
    if current.endswith(('.', '!', '?', ':')):
        return False
    
    # Don't continue if next line starts with bullet or special markers
    if next_stripped.startswith(('*', '-', '•', 'http', 'https', 'URL:', 'Title:')):
        return False
    
    # Don't continue if next line is a separator
    if next_stripped.startswith('=' * 10):
        return False
    
    # Don't continue if next line looks like a new paragraph (all caps, etc.)
    if next_stripped.isupper() and len(next_stripped) > 5:
        return False
    
    # Continue if current ends mid-word (letter) and next starts with lowercase
    if current[-1].isalpha() and next_stripped[0].islower():
        return True
    
    # Continue if current is long and ends with letter (likely wrapped)
    if len(current) >= 80 and current[-1].isalpha():
        return True
    
    return False


def fix_line_wrapping(lines: list) -> list:
    """Fix lines that were broken mid-word or mid-sentence due to column width."""
    result = []
    i = 0
    
    while i < len(lines):
        current = lines[i]
        
        # Keep merging while we find continuations
        while i + 1 < len(lines) and looks_like_continuation(current, lines[i + 1]):
            next_line = lines[i + 1].strip()
            # Join without space if current ends with letter and next starts with letter
            # (broken mid-word)
            if current[-1].isalpha() and next_line[0].islower():
                current = current.rstrip() + next_line
            else:
                current = current.rstrip() + ' ' + next_line
            i += 1
        
        result.append(current)
        i += 1
    
    return result


def clean_content(content: str) -> str:
    """Clean the entire content of a file."""
    # Normalize Unicode first
    content = normalize_unicode(content)
    
    lines = content.split('\n')
    cleaned_lines = []
    
    # Track state
    in_header = True
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
            in_header = True
            continue
        
        # Skip navigation section after separator
        if found_separator and in_header:
            stripped = line.strip()
            # Check if this looks like real content
            if stripped and not is_navigation_line(stripped):
                # Real content is usually longer than nav items
                if len(stripped) > 50:
                    in_header = False
                else:
                    # Check ahead for content
                    has_content = False
                    for j in range(i + 1, min(i + 5, len(lines))):
                        if len(lines[j].strip()) > 60 and not is_navigation_line(lines[j].strip()):
                            has_content = True
                            break
                    if has_content:
                        in_header = False
                    elif is_navigation_line(stripped):
                        continue
        
        if in_header and found_separator:
            continue
        
        # Skip navigation lines
        if is_navigation_line(line):
            continue
        
        # Clean the line
        cleaned = clean_line(line)
        
        # Skip empty lines at start
        if not cleaned_lines or cleaned_lines[-1].startswith('='):
            if not cleaned:
                continue
        
        cleaned_lines.append(cleaned)
    
    # Fix line wrapping
    cleaned_lines = fix_line_wrapping(cleaned_lines)
    
    # Join and final cleanup
    result = '\n'.join(cleaned_lines)
    
    # Remove excessive blank lines
    result = re.sub(r'\n{3,}', '\n\n', result)
    
    # Remove trailing whitespace from each line
    result = '\n'.join(line.rstrip() for line in result.split('\n'))
    
    return result.strip()


def process_file(filepath: Path) -> tuple[bool, str]:
    """Process a single file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        cleaned = clean_content(content)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(cleaned)
        
        original_len = len(content)
        cleaned_len = len(cleaned)
        reduction = ((original_len - cleaned_len) / original_len) * 100 if original_len > 0 else 0
        
        return True, f"Cleaned {filepath.name}: {original_len} -> {cleaned_len} bytes ({reduction:.1f}% reduction)"
    
    except Exception as e:
        return False, f"Error processing {filepath.name}: {str(e)}"


def main():
    """Process all txt files in the web directory."""
    web_dir = Path('/project/rcc/youzhi/user-guide/web')
    
    if not web_dir.exists():
        print(f"Directory not found: {web_dir}")
        return
    
    txt_files = list(web_dir.glob('*.txt'))
    print(f"Found {len(txt_files)} text files to process\n")
    
    success_count = 0
    error_count = 0
    
    for filepath in sorted(txt_files):
        if filepath.name.endswith('.py'):
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
