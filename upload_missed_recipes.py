#!/usr/bin/env python
# upload_missed_recipes.py - A tool to find and upload missed recipes

import os
import json
import random
import time
from datetime import datetime
import logging
from recipe_agent import RecipeVideoAgent  # Import from your main script

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("missed_uploads.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def load_all_recipes(json_path):
    """Load all recipes from JSON file with error handling"""
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            # Read the file and replace any control characters
            content = f.read()
            # Replace common problematic control characters
            for i in range(0, 32):
                if i not in [9, 10, 13]:  # Tab, LF, CR are allowed
                    content = content.replace(chr(i), '')
            
            # Parse the cleaned JSON
            data = json.loads(content)
            recipes = data.get('recipes', [])
            
        logger.info(f"Loaded {len(recipes)} recipes from JSON file")
        return recipes
    except Exception as e:
        logger.error(f"Failed to load recipes: {str(e)}")
        raise

def load_used_recipes():
    """Load previously used recipes"""
    used_recipes = set()
    if os.path.exists("used_recipes.json"):
        with open("used_recipes.json", 'r') as f:
            used_recipes = set(json.load(f))
    return used_recipes

def find_missed_recipes(all_recipes, used_recipes):
    """Find recipes that haven't been uploaded yet"""
    all_recipe_ids = {str(recipe['id']) for recipe in all_recipes}
    missed_recipe_ids = all_recipe_ids - used_recipes
    
    missed_recipes = [r for r in all_recipes if str(r['id']) in missed_recipe_ids]
    
    logger.info(f"Total recipes: {len(all_recipe_ids)}")
    logger.info(f"Uploaded recipes: {len(used_recipes)}")
    logger.info(f"Missed recipes: {len(missed_recipes)}")
    
    return missed_recipes

def generate_report(all_recipes, used_recipes):
    """Generate a report of missed recipes"""
    missed_recipes = find_missed_recipes(all_recipes, used_recipes)
    
    # Create a report file
    report_date = datetime.now().strftime('%Y-%m-%d')
    with open(f"missed_recipes_report_{report_date}.txt", 'w') as f:
        f.write(f"Missed Recipes Report - {report_date}\n")
        f.write(f"Total Recipes: {len(all_recipes)}\n")
        f.write(f"Uploaded Recipes: {len(used_recipes)}\n")
        f.write(f"Missed Recipes: {len(missed_recipes)}\n\n")
        
        if missed_recipes:
            f.write("Missed Recipes:\n")
            for recipe in missed_recipes:
                f.write(f"ID: {recipe['id']} - {recipe['dish_name']}\n")
    
    logger.info(f"Generated report: missed_recipes_report_{report_date}.txt")
    return missed_recipes

def upload_missed_recipes(recipe_json_path, credentials_path, max_uploads=None):
    """Find and upload missed recipes
    
    Args:
        recipe_json_path (str): Path to the recipe JSON file
        credentials_path (str): Path to Google API credentials file
        max_uploads (int, optional): Maximum number of uploads to perform
    """
    # Load all recipes and used recipes
    all_recipes = load_all_recipes(recipe_json_path)
    used_recipes = load_used_recipes()
    
    # Generate report and get missed recipes
    missed_recipes = generate_report(all_recipes, used_recipes)
    
    if not missed_recipes:
        logger.info("No missed recipes to upload.")
        return
    
    # Limit the number of uploads if specified
    if max_uploads and max_uploads > 0:
        missed_recipes = missed_recipes[:max_uploads]
        
    logger.info(f"Preparing to upload {len(missed_recipes)} missed recipes")
    
    # Create instance of RecipeVideoAgent
    agent = RecipeVideoAgent(recipe_json_path, credentials_path)
    
    # Authenticate once
    agent.authenticate()
    agent.load_recipes()
    
    # Upload each missed recipe
    for i, recipe in enumerate(missed_recipes):
        try:
            logger.info(f"Starting upload {i+1} of {len(missed_recipes)}: {recipe['dish_name']} (ID: {recipe['id']})")
            
            # Download video
            video_path = agent.download_video(recipe)
            
            # Upload to YouTube
            youtube_url = agent.upload_to_youtube(video_path, recipe)
            
            # Clean up
            agent.cleanup(video_path)
            
            logger.info(f"Successfully uploaded recipe ID {recipe['id']}: {youtube_url}")
            
            # Add delay between uploads
            if i < len(missed_recipes) - 1:
                delay = 60  # 1 minute delay
                logger.info(f"Waiting {delay} seconds before next upload...")
                time.sleep(delay)
                
        except Exception as e:
            logger.error(f"Failed to upload recipe ID {recipe['id']}: {str(e)}")
            continue

if __name__ == "__main__":
    # Configuration
    RECIPE_JSON_PATH = "paste.txt"  # Your JSON file path
    CREDENTIALS_PATH = "credentials.json"  # Your credentials file path
    MAX_UPLOADS = 5  # Maximum number of missed recipes to upload at once
    
    upload_missed_recipes(RECIPE_JSON_PATH, CREDENTIALS_PATH, MAX_UPLOADS)