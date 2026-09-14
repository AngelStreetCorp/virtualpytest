"""
Simple Image Mosaic Generator for Zapping Analysis

Creates visual mosaics of analyzed images to help understand zapping detection failures.
"""

import os
from typing import List, Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import tempfile


def create_zapping_failure_mosaic(image_paths: List[str], 
                                detection_method: str,
                                analysis_info: Dict[str, Any] = None) -> Optional[str]:
    """
    Create a simple mosaic image showing all analyzed images for zapping failure.
    
    Args:
        image_paths: List of full paths to analyzed images
        detection_method: 'blackscreen', 'freeze', or 'both_failed'
        analysis_info: Optional analysis data (freeze comparisons, etc.)
        
    Returns:
        Path to created mosaic image or None if failed
    """
    try:
        if not image_paths:
            return None
        
        # Simple grid configuration - 5 columns max
        grid_cols = min(5, len(image_paths))
        grid_rows = (len(image_paths) + grid_cols - 1) // grid_cols
        
        # Thumbnail size
        thumb_width, thumb_height = 200, 150
        
        # Calculate mosaic dimensions
        mosaic_width = grid_cols * thumb_width
        mosaic_height = 40 + (grid_rows * (thumb_height + 25))  # Header + images + timestamp space
        
        # Create mosaic canvas
        mosaic = Image.new('RGB', (mosaic_width, mosaic_height), color='white')
        draw = ImageDraw.Draw(mosaic)
        
        # Try to load font
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", 12)
            title_font = ImageFont.truetype("/System/Library/Fonts/Arial.ttf", 14)
        except:
            font = ImageFont.load_default()
            title_font = font
        
        # Draw title
        title = f"Zapping Failure Analysis - {detection_method.upper()} ({len(image_paths)} images)"
        draw.text((10, 10), title, fill='black', font=title_font)
        
        # Get freeze comparison data if available
        comparisons = []
        if analysis_info and detection_method == 'freeze':
            comparisons = analysis_info.get('comparisons', [])
        
        # Process each image
        for idx, image_path in enumerate(image_paths):
            if not os.path.exists(image_path):
                continue
                
            row = idx // grid_cols
            col = idx % grid_cols
            
            x = col * thumb_width
            y = 40 + (row * (thumb_height + 25))
            
            try:
                # Load and resize image
                img = Image.open(image_path)
                img_resized = img.resize((thumb_width, thumb_height), Image.Resampling.LANCZOS)
                mosaic.paste(img_resized, (x, y))
                
                # Extract sequence number from filename and use file mtime for timestamp
                filename = os.path.basename(image_path)
                timestamp = "Unknown"
                if filename.startswith('capture_') and filename.endswith('.jpg'):
                    try:
                        # Use file modification time for timestamp display
                        file_mtime = os.path.getmtime(image_path)
                        dt = datetime.fromtimestamp(file_mtime)
                        timestamp = dt.strftime('%H:%M:%S')
                    except:
                        pass
                
                # Draw timestamp
                draw.rectangle([x, y + thumb_height, x + thumb_width, y + thumb_height + 25], fill='black')
                draw.text((x + 5, y + thumb_height + 5), timestamp, fill='white', font=font)
                
                # Draw freeze analysis info if available
                if idx < len(comparisons):
                    comp = comparisons[idx]
                    diff = comp.get('difference', 0)
                    frozen = comp.get('frozen', False)
                    
                    # Color code based on difference
                    if frozen:
                        color = 'red'
                        text = f"FROZEN {diff:.0f}%"
                    elif diff < 30:
                        color = 'yellow'
                        text = f"{diff:.0f}%"
                    else:
                        color = 'green'
                        text = f"{diff:.0f}%"
                    
                    # Draw analysis overlay
                    draw.rectangle([x + thumb_width - 80, y + 5, x + thumb_width - 5, y + 20], fill=color)
                    draw.text((x + thumb_width - 75, y + 7), text, fill='black', font=font)
                
            except Exception as e:
                # Draw error placeholder
                draw.rectangle([x, y, x + thumb_width, y + thumb_height], fill='lightgray')
                draw.text((x + 5, y + 5), f"Error: {os.path.basename(image_path)}", fill='red', font=font)
        
        # Save mosaic
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = os.path.join(tempfile.gettempdir(), f"zap_failure_{detection_method}_{timestamp}.jpg")
        mosaic.save(output_path, 'JPEG', quality=85)
        
        return output_path
        
    except Exception as e:
        print(f"Failed to create mosaic: {e}")
        return None
