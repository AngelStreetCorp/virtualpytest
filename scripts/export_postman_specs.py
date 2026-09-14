#!/usr/bin/env python3
"""
Generate Beautiful HTML Documentation from Local OpenAPI Specifications
Reads YAML files from docs/api/specs/ and generates HTML documentation
"""

import sys
import subprocess
from pathlib import Path

# Configuration
YAML_DIR = Path(__file__).parent.parent / "docs" / "api" / "specs"
DOCS_DIR = Path(__file__).parent.parent / "docs" / "api" / "docs"

# Colors
class Colors:
    BLUE = '\033[0;34m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    NC = '\033[0m'

def print_header():
    print(f"{Colors.BLUE}╔══════════════════════════════════════════════════════════╗{Colors.NC}")
    print(f"{Colors.BLUE}║   VirtualPyTest - API Documentation Generator          ║{Colors.NC}")
    print(f"{Colors.BLUE}╚══════════════════════════════════════════════════════════╝{Colors.NC}\n")

def check_node_tools():
    """Check if required Node.js tools are installed."""
    try:
        subprocess.run(['npx', '--version'], capture_output=True, check=True)
        return True
    except:
        return False

def inject_auto_expand_script(html_file):
    """Inject JavaScript to auto-expand menu items in ReDoc HTML."""
    auto_expand_script = """
    // Auto-expand all menu items after Redoc loads
    setTimeout(function() {
      var menuLabels = document.querySelectorAll('[data-item-id] > label');
      menuLabels.forEach(function(label) {
        var svg = label.querySelector('svg');
        if (svg && !label.parentElement.classList.contains('active')) {
          label.click();
        }
      });
    }, 300);
    """
    
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Insert the script before the closing </script></body> tags
        content = content.replace(
            '    </script>\n</body>',
            f'{auto_expand_script}    </script>\n</body>'
        )
        
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        print(f"  {Colors.YELLOW}⚠{Colors.NC} Could not inject auto-expand script: {e}")

def generate_html_docs():
    """Generate beautiful HTML documentation using redoc-cli."""
    print(f"\n{Colors.BLUE}╔══════════════════════════════════════════════════════════╗{Colors.NC}")
    print(f"{Colors.BLUE}║   Generating Beautiful HTML Documentation               ║{Colors.NC}")
    print(f"{Colors.BLUE}╚══════════════════════════════════════════════════════════╝{Colors.NC}\n")
    
    if not check_node_tools():
        print(f"{Colors.RED}✗{Colors.NC} Node.js/npx not found. Skipping HTML generation.\n")
        print(f"{Colors.YELLOW}Install Node.js to generate documentation:{Colors.NC}")
        print(f"  brew install node  # or download from nodejs.org\n")
        return False
    
    # Create docs directory
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Generate HTML for each spec
    yaml_files = list(YAML_DIR.glob("*.yaml"))
    total = len(yaml_files)
    
    for index, yaml_file in enumerate(yaml_files, 1):
        spec_name = yaml_file.stem
        html_file = DOCS_DIR / f"{spec_name}.html"
        
        print(f"{Colors.BLUE}[{index}/{total}]{Colors.NC} {spec_name}.yaml → {spec_name}.html")
        
        try:
            # Use redoc-cli to generate standalone HTML
            subprocess.run([
                'npx', '-y', 'redoc-cli', 'bundle',
                str(yaml_file),
                '-o', str(html_file),
                '--title', f'VirtualPyTest API - {spec_name.replace("-", " ").title()}'
            ], capture_output=True, check=True, text=True)
            
            # Post-process: Add auto-expand script for menu items
            inject_auto_expand_script(html_file)
            
            print(f"  {Colors.GREEN}✓{Colors.NC} Generated: {html_file}\n")
        except subprocess.CalledProcessError as e:
            print(f"  {Colors.RED}✗{Colors.NC} Failed: {e.stderr}\n")
    
    # Create index.html
    create_index_html(yaml_files)
    
    return True

def create_index_html(yaml_files):
    """Create an index page linking to all documentation."""
    index_path = DOCS_DIR / "index.html"
    
    server_specs = [f for f in yaml_files if f.stem.startswith('server-')]
    
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>API Documentation</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; 
               background: #0f172a; 
               padding: 20px; min-height: 100vh; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .section {{ background: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 20px; margin-bottom: 20px; 
                    box-shadow: 0 4px 20px rgba(0,0,0,0.2); }}
        .section h2 {{ color: #94a3b8; margin-bottom: 16px; font-size: 1rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }}
        .api-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }}
        .api-card {{ background: #334155; 
                     padding: 14px 16px; border-radius: 6px; transition: all 0.2s; 
                     border-left: 3px solid #64748b; }}
        .api-card:hover {{ transform: translateY(-2px); box-shadow: 0 6px 16px rgba(0,0,0,0.3); background: #3f4f63; }}
        .api-card a {{ text-decoration: none; color: #f1f5f9; font-weight: 500; font-size: 0.95rem; }}
        .api-card p {{ color: #94a3b8; margin-top: 4px; font-size: 0.8rem; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="section">
            <h2>📡 Server APIs ({len(server_specs)})</h2>
            <div class="api-grid">
"""
    
    for spec_file in sorted(server_specs):
        name = spec_file.stem.replace('server-', '').replace('-', ' ').title()
        html_content += f"""                <div class="api-card">
                    <a href="{spec_file.stem}.html">{name}</a>
                    <p>Server-side {name.lower()} endpoints</p>
                </div>
"""
    
    html_content += f"""            </div>
        </div>
    </div>
</body>
</html>
"""
    
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"{Colors.GREEN}✓{Colors.NC} Created index: {index_path}\n")

def print_footer(total_count, docs_generated):
    print(f"\n{Colors.GREEN}╔══════════════════════════════════════════════════════════╗{Colors.NC}")
    print(f"{Colors.GREEN}║   Complete!                                             ║{Colors.NC}")
    print(f"{Colors.GREEN}╚══════════════════════════════════════════════════════════╝{Colors.NC}\n")
    print(f"{Colors.BLUE}Source Specs:{Colors.NC} {YAML_DIR} ({total_count} specs)")
    if docs_generated:
        print(f"{Colors.BLUE}HTML Docs:{Colors.NC}   {DOCS_DIR} ({total_count} pages generated)")
        print(f"\n{Colors.YELLOW}Open documentation:{Colors.NC}")
        print(f"  file://{DOCS_DIR / 'index.html'}\n")
    else:
        print(f"\n{Colors.YELLOW}To generate HTML docs, install Node.js:{Colors.NC}")
        print(f"  brew install node\n")

def main():
    print_header()
    
    # Check if YAML directory exists
    if not YAML_DIR.exists():
        print(f"{Colors.RED}✗{Colors.NC} Error: YAML directory not found: {YAML_DIR}")
        print(f"\n{Colors.YELLOW}Please ensure OpenAPI specs exist in:{Colors.NC}")
        print(f"  {YAML_DIR}\n")
        sys.exit(1)
    
    # Find all YAML files
    yaml_files = list(YAML_DIR.glob("*.yaml"))
    if not yaml_files:
        print(f"{Colors.RED}✗{Colors.NC} Error: No YAML files found in {YAML_DIR}\n")
        sys.exit(1)
    
    print(f"{Colors.GREEN}✓{Colors.NC} Found {len(yaml_files)} OpenAPI specs in: {Colors.YELLOW}{YAML_DIR}{Colors.NC}\n")
    
    # Generate HTML documentation
    docs_generated = generate_html_docs()
    
    print_footer(len(yaml_files), docs_generated)

if __name__ == "__main__":
    main()
