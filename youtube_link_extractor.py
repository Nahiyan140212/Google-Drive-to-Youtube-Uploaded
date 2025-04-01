#!/usr/bin/env python
# youtube_link_extractor.py - Extract YouTube links from log file and update recipe JSON

import os
import re
import json
import argparse
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("link_extractor.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def extract_youtube_links(log_file_path):
    """
    Extract YouTube video links and recipe IDs from the log file
    
    Args:
        log_file_path (str): Path to the log file
        
    Returns:
        dict: Dictionary with recipe IDs as keys and YouTube links as values
    """
    youtube_links = {}
    recipe_id_pattern = re.compile(r'Processing recipe: (.*?) \(ID: (\d+)\)')
    youtube_link_pattern = re.compile(r'Video uploaded successfully: (https://www\.youtube\.com/watch\?v=[\w-]+)')
    
    current_recipe_id = None
    
    try:
        with open(log_file_path, 'r', encoding='utf-8') as log_file:
            for line in log_file:
                # Check for recipe ID
                id_match = recipe_id_pattern.search(line)
                if id_match:
                    recipe_name = id_match.group(1)
                    current_recipe_id = id_match.group(2)
                    logger.info(f"Found recipe: {recipe_name} (ID: {current_recipe_id})")
                
                # Check for YouTube link
                link_match = youtube_link_pattern.search(line)
                if link_match and current_recipe_id:
                    youtube_link = link_match.group(1)
                    youtube_links[current_recipe_id] = youtube_link
                    logger.info(f"Found YouTube link for recipe ID {current_recipe_id}: {youtube_link}")
                    current_recipe_id = None  # Reset to avoid duplicate matching
    
    except Exception as e:
        logger.error(f"Error reading log file: {str(e)}")
    
    logger.info(f"Extracted {len(youtube_links)} YouTube links from log file")
    return youtube_links

def update_recipes_json(recipes_json_path, youtube_links):
    """
    Update recipes JSON file with YouTube links
    
    Args:
        recipes_json_path (str): Path to the recipes JSON file
        youtube_links (dict): Dictionary with recipe IDs as keys and YouTube links as values
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Load existing recipes JSON
        with open(recipes_json_path, 'r', encoding='utf-8') as f:
            recipes_data = json.load(f)
        
        # Keep track of which recipes were updated
        updated_count = 0
        
        # Update each recipe with its YouTube link if available
        for recipe in recipes_data.get('recipes', []):
            recipe_id = str(recipe.get('id'))
            if recipe_id in youtube_links:
                # Only add youtube_link if it doesn't already exist or is different
                if 'youtube_link' not in recipe or recipe['youtube_link'] != youtube_links[recipe_id]:
                    recipe['youtube_link'] = youtube_links[recipe_id]
                    updated_count += 1
                    logger.info(f"Updated recipe ID {recipe_id} ({recipe['dish_name']}) with YouTube link")
        
        # Create backup of original file
        backup_path = recipes_json_path + '.bak'
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(recipes_data, f, indent=4)
        logger.info(f"Created backup of original JSON at {backup_path}")
        
        # Save updated recipes JSON
        with open(recipes_json_path, 'w', encoding='utf-8') as f:
            json.dump(recipes_data, f, indent=4)
        
        logger.info(f"Updated {updated_count} recipes with YouTube links")
        return True
    
    except Exception as e:
        logger.error(f"Error updating recipes JSON: {str(e)}")
        return False

def create_youtube_links_json(youtube_links, output_path='youtube_links.json'):
    """
    Create a separate JSON file containing only recipe IDs and YouTube links
    
    Args:
        youtube_links (dict): Dictionary with recipe IDs as keys and YouTube links as values
        output_path (str): Path to save the output JSON file
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Create structured data
        links_data = {
            "youtube_links": [
                {
                    "recipe_id": int(recipe_id),
                    "youtube_link": link
                }
                for recipe_id, link in youtube_links.items()
            ]
        }
        
        # Save to JSON file
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(links_data, f, indent=4)
        
        logger.info(f"Created YouTube links JSON at {output_path}")
        return True
    
    except Exception as e:
        logger.error(f"Error creating YouTube links JSON: {str(e)}")
        return False

def main():
    parser = argparse.ArgumentParser(description='Extract YouTube links from log file and update recipes JSON')
    parser.add_argument('--log', default='robust_uploader.log', help='Path to the log file')
    parser.add_argument('--recipes', default='recipes.json', help='Path to the recipes JSON file')
    parser.add_argument('--output', default='youtube_links.json', help='Path to save the output YouTube links JSON')
    parser.add_argument('--no-update', action='store_true', help='Do not update the recipes JSON file')
    
    args = parser.parse_args()
    
    # Extract YouTube links from log file
    youtube_links = extract_youtube_links(args.log)
    
    if not youtube_links:
        logger.warning("No YouTube links found in log file")
        return
    
    # Create YouTube links JSON
    create_youtube_links_json(youtube_links, args.output)
    
    # Update recipes JSON if requested
    if not args.no_update:
        update_recipes_json(args.recipes, youtube_links)

if __name__ == "__main__":
    main()


#run with python youtube_link_extractor.py --log robust_uploader.log --recipes recipes.json