#!/usr/bin/env python
# fix_timeouts.py - Modified version to handle timeouts better

import os
import json
import random
import time
from datetime import datetime
import logging
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import googleapiclient.errors
import google.auth.exceptions
import socket

# Increase default timeout for socket operations
socket.setdefaulttimeout(300)  # 5 minutes timeout

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("recipe_agent_fixed.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Google API scopes
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/youtube.upload'
]

def download_video_with_retry(drive_service, file_id, recipe_id, max_retries=3):
    """Download video with retry logic for timeouts"""
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            request = drive_service.files().get_media(fileId=file_id)
            
            # Create a BytesIO object to store the downloaded video
            video_file = io.BytesIO()
            downloader = MediaIoBaseDownload(video_file, request, chunksize=1024*1024)
            
            # Download the video
            done = False
            while not done:
                status, done = downloader.next_chunk()
                logger.info(f"Download progress: {int(status.progress() * 100)}%")
            
            # Save the downloaded file to disk
            video_path = f"temp_video_{recipe_id}.mp4"
            with open(video_path, 'wb') as f:
                f.write(video_file.getvalue())
            
            logger.info(f"Successfully downloaded video to {video_path}")
            return video_path
            
        except socket.timeout:
            retry_count += 1
            logger.warning(f"Download timed out. Retry {retry_count} of {max_retries}...")
            time.sleep(5)  # Wait before retrying
        except Exception as e:
            logger.error(f"Error downloading video: {str(e)}")
            raise
    
    # If we get here, all retries failed
    raise Exception(f"Failed to download video after {max_retries} retries")

def process_single_recipe(recipe_json_path, credentials_path, specific_id=None):
    """Process a single recipe with better timeout handling
    
    Args:
        recipe_json_path (str): Path to recipe JSON file
        credentials_path (str): Path to Google API credentials
        specific_id (str, optional): Specific recipe ID to process
    """
    try:
        # Initialize credentials
        creds = None
        token_path = 'token.json'
        
        # Check if token.json exists with valid credentials
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_info(
                json.load(open(token_path)), SCOPES)
        
        # If no valid credentials, authenticate user
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
            
            # Save credentials for future use
            with open(token_path, 'w') as token:
                token.write(creds.to_json())
        
        # Build services
        drive_service = build('drive', 'v3', credentials=creds)
        youtube_service = build('youtube', 'v3', credentials=creds)
        
        # Load recipes
        with open(recipe_json_path, 'r') as f:
            data = json.load(f)
            recipes = data.get('recipes', [])
        
        # Load used recipes
        used_recipes = set()
        used_recipes_file = "used_recipes.json"
        if os.path.exists(used_recipes_file):
            with open(used_recipes_file, 'r') as f:
                used_recipes = set(json.load(f))
        
        # Select recipe
        if specific_id:
            # Find the specific recipe by ID
            selected_recipe = next((r for r in recipes if str(r.get('id')) == specific_id), None)
            if not selected_recipe:
                logger.error(f"Recipe with ID {specific_id} not found")
                return
        else:
            # Select an unused recipe randomly
            available_recipes = [r for r in recipes if str(r.get('id')) not in used_recipes]
            if not available_recipes:
                logger.info("All recipes have been used. Resetting used recipes list.")
                used_recipes = set()
                available_recipes = recipes
            
            selected_recipe = random.choice(available_recipes)
        
        logger.info(f"Processing recipe: {selected_recipe['dish_name']} (ID: {selected_recipe['id']})")
        
        # Extract file ID
        file_id = None
        drive_url = selected_recipe['public_url']
        if '/file/d/' in drive_url:
            file_id = drive_url.split('/file/d/')[1].split('/')[0]
        
        if not file_id:
            logger.error(f"Invalid Google Drive URL: {drive_url}")
            return
        
        # Download video with improved timeout handling
        video_path = download_video_with_retry(drive_service, file_id, selected_recipe['id'])
        
        # Upload to YouTube
        video_title = f"{selected_recipe['dish_name']} Recipe - {datetime.now().strftime('%Y-%m-%d')}"
        
        ingredients_list = "\n".join([f"- {ingredient}" for ingredient in selected_recipe['ingredients']])
        instructions_list = "\n".join([f"{i+1}. {instruction}" 
                                     for i, instruction in enumerate(selected_recipe['instructions'])])
        
        video_description = (
            f"{selected_recipe['dish_name']}\n\n"
            f"Prep Time: {selected_recipe['prep_time']}\n"
            f"Cook Time: {selected_recipe['cook_time']}\n"
            f"Yield: {selected_recipe['yield']}\n\n"
            f"INGREDIENTS:\n{ingredients_list}\n\n"
            f"INSTRUCTIONS:\n{instructions_list}\n\n"
            f"Follow for more delicious recipes daily!"
        )
        
        # Set video tags
        tags = [
            selected_recipe['dish_name'], 
            selected_recipe['dish_type'], 
            selected_recipe['taste_category'], 
            "recipe", "cooking", "food", 
            "homemade", "chef", "delicious"
        ]
        
        # Create upload request body
        body = {
            'snippet': {
                'title': video_title,
                'description': video_description,
                'tags': tags,
                'categoryId': '22'  # 22 is the category ID for "People & Blogs"
            },
            'status': {
                'privacyStatus': 'public',  # or 'private', 'unlisted'
                'selfDeclaredMadeForKids': False
            }
        }
        
        # Upload the video
        with open(video_path, 'rb') as video_file:
            upload_request = youtube_service.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=googleapiclient.http.MediaIoBaseUpload(
                    video_file, mimetype='video/mp4', resumable=True,
                    chunksize=1024*1024  # 1MB chunks
                )
            )
            
            # Execute the upload with progress tracking
            response = None
            while response is None:
                try:
                    status, response = upload_request.next_chunk()
                    if status:
                        logger.info(f"Upload progress: {int(status.progress() * 100)}%")
                except socket.timeout:
                    logger.warning("Upload timed out, retrying...")
                    time.sleep(5)
                    continue
            
        logger.info(f"Video uploaded successfully! Video ID: {response['id']}")
        
        # Mark recipe as used
        used_recipes.add(str(selected_recipe['id']))
        with open(used_recipes_file, 'w') as f:
            json.dump(list(used_recipes), f)
        
        # Clean up
        if os.path.exists(video_path):
            os.remove(video_path)
            logger.info(f"Removed temporary file: {video_path}")
        
        return f"https://www.youtube.com/watch?v={response['id']}"
        
    except Exception as e:
        logger.error(f"Process failed: {str(e)}")
        return None

if __name__ == "__main__":
    # Configuration
    RECIPE_JSON_PATH = "recipes.json"  # Update with your filename
    CREDENTIALS_PATH = "credentials.json"
    NUM_UPLOADS = 10
    
    success_count = 0
    
    # Attempt to upload multiple videos
    for i in range(NUM_UPLOADS):
        logger.info(f"Starting upload {i+1} of {NUM_UPLOADS}")
        
        # Process a single recipe
        youtube_url = process_single_recipe(RECIPE_JSON_PATH, CREDENTIALS_PATH)
        
        if youtube_url:
            success_count += 1
            logger.info(f"Upload {i+1} completed: {youtube_url}")
        else:
            logger.error(f"Upload {i+1} failed")
        
        # Add a longer delay between uploads
        if i < NUM_UPLOADS - 1:
            delay = 120  # 2 minute delay between uploads
            logger.info(f"Waiting {delay} seconds before next upload...")
            time.sleep(delay)
    
    logger.info(f"Uploaded {success_count} of {NUM_UPLOADS} videos successfully")