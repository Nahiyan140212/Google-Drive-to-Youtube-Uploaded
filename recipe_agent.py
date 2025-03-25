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

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("recipe_agent.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Google API scopes
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/youtube.upload'
]

class RecipeVideoAgent:
    def __init__(self, recipe_json_path, credentials_path):
        """
        Initialize the Recipe Video Agent
        
        Args:
            recipe_json_path (str): Path to the JSON file containing recipe data
            credentials_path (str): Path to the Google API credentials file
        """
        self.recipe_json_path = recipe_json_path
        self.credentials_path = credentials_path
        self.credentials = None
        self.drive_service = None
        self.youtube_service = None
        self.recipes = []
        self.used_recipes = set()
        self.used_recipes_file = "used_recipes.json"
        
        # Load previously used recipes if file exists
        if os.path.exists(self.used_recipes_file):
            with open(self.used_recipes_file, 'r') as f:
                self.used_recipes = set(json.load(f))
    
    def authenticate(self):
        """Authenticate with Google APIs"""
        try:
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
                        self.credentials_path, SCOPES)
                    creds = flow.run_local_server(port=0)
                
                # Save credentials for future use
                with open(token_path, 'w') as token:
                    token.write(creds.to_json())
            
            self.credentials = creds
            self.drive_service = build('drive', 'v3', credentials=creds)
            self.youtube_service = build('youtube', 'v3', credentials=creds)
            logger.info("Successfully authenticated with Google APIs")
            
        except Exception as e:
            logger.error(f"Authentication failed: {str(e)}")
            raise
    
    def load_recipes(self):
        """Load recipes from JSON file"""
        try:
            with open(self.recipe_json_path, 'r') as f:
                data = json.load(f)
                self.recipes = data.get('recipes', [])
            logger.info(f"Loaded {len(self.recipes)} recipes from JSON file")
        except Exception as e:
            logger.error(f"Failed to load recipes: {str(e)}")
            raise
    
    def select_recipe(self):
        """Select a recipe that hasn't been used yet"""
        available_recipes = [recipe for recipe in self.recipes 
                            if str(recipe.get('id')) not in self.used_recipes]
        
        if not available_recipes:
            logger.info("All recipes have been used. Resetting used recipes list.")
            self.used_recipes = set()
            available_recipes = self.recipes
        
        selected_recipe = random.choice(available_recipes)
        logger.info(f"Selected recipe: {selected_recipe['dish_name']} (ID: {selected_recipe['id']})")
        return selected_recipe
    
    def download_video(self, recipe):
        """Download video from Google Drive using public_url"""
        try:
            file_id = self._extract_file_id(recipe['public_url'])
            if not file_id:
                raise ValueError(f"Invalid Google Drive URL: {recipe['public_url']}")
            
            request = self.drive_service.files().get_media(fileId=file_id)
            
            # Create a BytesIO object to store the downloaded video
            video_file = io.BytesIO()
            downloader = MediaIoBaseDownload(video_file, request)
            
            # Download the video
            done = False
            while not done:
                status, done = downloader.next_chunk()
                logger.info(f"Download progress: {int(status.progress() * 100)}%")
            
            # Save the downloaded file to disk
            video_path = f"temp_video_{recipe['id']}.mp4"
            with open(video_path, 'wb') as f:
                f.write(video_file.getvalue())
            
            logger.info(f"Successfully downloaded video to {video_path}")
            return video_path
            
        except googleapiclient.errors.HttpError as e:
            logger.error(f"HTTP error downloading video: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Failed to download video: {str(e)}")
            raise
    
    def _extract_file_id(self, drive_url):
        """Extract file ID from Google Drive URL"""
        if '/file/d/' in drive_url:
            file_id = drive_url.split('/file/d/')[1].split('/')[0]
            return file_id
        return None
    
    def upload_to_youtube(self, video_path, recipe):
        """Upload video to YouTube"""
        try:
            # Create video metadata
            video_title = f"{recipe['dish_name']} Recipe - {datetime.now().strftime('%Y-%m-%d')}"
            
            ingredients_list = "\n".join([f"- {ingredient}" for ingredient in recipe['ingredients']])
            instructions_list = "\n".join([f"{i+1}. {instruction}" 
                                         for i, instruction in enumerate(recipe['instructions'])])
            
            video_description = (
                f"{recipe['dish_name']}\n\n"
                f"Prep Time: {recipe['prep_time']}\n"
                f"Cook Time: {recipe['cook_time']}\n"
                f"Yield: {recipe['yield']}\n\n"
                f"INGREDIENTS:\n{ingredients_list}\n\n"
                f"INSTRUCTIONS:\n{instructions_list}\n\n"
                f"Follow for more delicious recipes daily!"
            )
            
            # Set video tags
            tags = [
                recipe['dish_name'], 
                recipe['dish_type'], 
                recipe['taste_category'], 
                "recipe", "cooking", "food", 
                "homemade", "chef", "delicious"
            ]
            
            # Add individual ingredients as tags
            for ingredient in recipe['ingredients']:
                # Extract main ingredient (remove measurements and extra details)
                main_ingredient = ingredient.split(',')[0].split()[-1]
                if main_ingredient not in tags:
                    tags.append(main_ingredient)
            
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
            
            # Open the video file
            with open(video_path, 'rb') as video_file:
                # Upload the video
                upload_request = self.youtube_service.videos().insert(
                    part=','.join(body.keys()),
                    body=body,
                    media_body=googleapiclient.http.MediaIoBaseUpload(
                        video_file, mimetype='video/mp4', resumable=True
                    )
                )
                
                # Execute the upload and track progress
                response = None
                while response is None:
                    status, response = upload_request.next_chunk()
                    if status:
                        logger.info(f"Upload progress: {int(status.progress() * 100)}%")
            
            logger.info(f"Video uploaded successfully! Video ID: {response['id']}")
            
            # Mark recipe as used
            self.used_recipes.add(str(recipe['id']))
            with open(self.used_recipes_file, 'w') as f:
                json.dump(list(self.used_recipes), f)
            
            # Return YouTube video URL
            return f"https://www.youtube.com/watch?v={response['id']}"
            
        except googleapiclient.errors.HttpError as e:
            logger.error(f"HTTP error uploading to YouTube: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Failed to upload to YouTube: {str(e)}")
            raise
    
    def cleanup(self, video_path):
        """Clean up temporary files"""
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
                logger.info(f"Removed temporary file: {video_path}")
        except Exception as e:
            logger.error(f"Failed to clean up file {video_path}: {str(e)}")
    
    def run(self):
        """Run the complete workflow"""
        try:
            logger.info("Starting recipe video agent workflow")
            
            # Authenticate with Google APIs
            self.authenticate()
            
            # Load recipes
            self.load_recipes()
            
            # Select a recipe
            recipe = self.select_recipe()
            
            # Download video
            video_path = self.download_video(recipe)
            
            # Upload to YouTube
            youtube_url = self.upload_to_youtube(video_path, recipe)
            
            # Clean up
            self.cleanup(video_path)
            
            logger.info(f"Workflow completed successfully. Video published at: {youtube_url}")
            return youtube_url
            
        except Exception as e:
            logger.error(f"Workflow failed: {str(e)}")
            raise


if __name__ == "__main__":
    # Configuration
    RECIPE_JSON_PATH = "recipes.json"  # Path to your recipe JSON file
    CREDENTIALS_PATH = "credentials.json"  # Path to your Google API credentials
    UPLOADS_PER_DAY = 10  # Number of videos to upload daily
    
    agent = RecipeVideoAgent(RECIPE_JSON_PATH, CREDENTIALS_PATH)
    
    # Run multiple uploads
    for i in range(UPLOADS_PER_DAY):
        try:
            logger.info(f"Starting upload {i+1} of {UPLOADS_PER_DAY}")
            youtube_url = agent.run()
            logger.info(f"Upload {i+1} completed: {youtube_url}")
            
            # Add a delay between uploads to avoid rate limits
            if i < UPLOADS_PER_DAY - 1:
                delay = 60  # 1 minute delay between uploads
                logger.info(f"Waiting {delay} seconds before next upload...")
                time.sleep(delay)
                
        except Exception as e:
            logger.error(f"Upload {i+1} failed: {str(e)}")
            # Continue with next upload even if this one fails
            continue