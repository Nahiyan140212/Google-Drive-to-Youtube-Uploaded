#!/usr/bin/env python
# sequential_uploader.py - Upload one recipe video at a time with improved timeout handling
#!/usr/bin/env python
# robust_uploader.py - Enhanced recipe video uploader with compression and resume capability

import os
import json
import time
import socket
import shutil
import argparse
import subprocess
import logging
from datetime import datetime
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
import io
import googleapiclient.errors
import google.auth.exceptions
import random
import re

# Significantly increase default timeout for socket operations
socket.setdefaulttimeout(1800)  # 30 minutes timeout

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("robust_uploader.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Google API scopes
SCOPES = [
    'https://www.googleapis.com/auth/drive.readonly',
    'https://www.googleapis.com/auth/youtube.upload'
]

class RobustUploader:
    def __init__(self, recipe_json_path, credentials_path):
        """
        Initialize the Robust Uploader
        
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
        self.resume_data_file = "resume_data.json"
        self.temp_dir = "temp_videos"
        
        # Create temp directory if it doesn't exist
        if not os.path.exists(self.temp_dir):
            os.makedirs(self.temp_dir)
        
        # Load previously used recipes if file exists
        if os.path.exists(self.used_recipes_file):
            with open(self.used_recipes_file, 'r') as f:
                self.used_recipes = set(json.load(f))
        
        logger.info(f"Loaded {len(self.used_recipes)} previously used recipe IDs")
        
        # Load resume data if file exists
        self.resume_data = {}
        if os.path.exists(self.resume_data_file):
            with open(self.resume_data_file, 'r') as f:
                try:
                    self.resume_data = json.load(f)
                    logger.info(f"Loaded resume data for {len(self.resume_data)} recipes")
                except json.JSONDecodeError:
                    logger.warning("Invalid resume data file. Starting fresh.")
    
    def authenticate(self):
        """Authenticate with Google APIs with enhanced retry logic"""
        try:
            creds = None
            token_path = 'token.json'
            max_retries = 3
            retry_count = 0
            
            while retry_count < max_retries:
                try:
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
                    
                    break  # Authentication successful
                except socket.timeout:
                    retry_count += 1
                    logger.warning(f"Authentication timed out. Retry {retry_count}/{max_retries}...")
                    time.sleep(5)
                except Exception as e:
                    logger.error(f"Authentication error: {str(e)}")
                    retry_count += 1
                    if retry_count >= max_retries:
                        raise
                    time.sleep(5)
            
            self.credentials = creds
            self.drive_service = build('drive', 'v3', credentials=creds)
            self.youtube_service = build('youtube', 'v3', credentials=creds)
            logger.info("Successfully authenticated with Google APIs")
            
        except Exception as e:
            logger.error(f"Authentication failed after multiple retries: {str(e)}")
            raise
    
    def load_recipes(self):
        """Load recipes from JSON file with robust error handling"""
        try:
            with open(self.recipe_json_path, 'r', encoding='utf-8') as f:
                # Read the file and replace any control characters
                content = f.read()
                # Replace common problematic control characters
                for i in range(0, 32):
                    if i not in [9, 10, 13]:  # Tab, LF, CR are allowed
                        content = content.replace(chr(i), '')
                
                # Parse the cleaned JSON
                data = json.loads(content)
                self.recipes = data.get('recipes', [])
                
            logger.info(f"Loaded {len(self.recipes)} recipes from JSON file")
        except Exception as e:
            logger.error(f"Failed to load recipes: {str(e)}")
            raise
    
    def get_next_recipe(self):
        """Get the next recipe that hasn't been uploaded yet"""
        available_recipes = [recipe for recipe in self.recipes 
                            if str(recipe.get('id')) not in self.used_recipes]
        
        if not available_recipes:
            logger.info("All recipes have been used. No more recipes to upload.")
            return None
        
        # First check if there's a recipe in progress to resume
        resume_recipe_id = None
        for recipe_id, data in self.resume_data.items():
            if data.get('status') == 'downloading' or data.get('status') == 'compressing' or data.get('status') == 'uploading':
                resume_recipe_id = recipe_id
                break
        
        if resume_recipe_id:
            # Find the recipe to resume
            for recipe in available_recipes:
                if str(recipe.get('id')) == resume_recipe_id:
                    logger.info(f"Resuming recipe: {recipe['dish_name']} (ID: {recipe['id']})")
                    return recipe
        
        # Otherwise, sort by ID and get the next one
        available_recipes.sort(key=lambda r: int(r.get('id', 0)))
        next_recipe = available_recipes[0]
        
        # If we have a lot of recipes, occasionally pick a random one to avoid getting stuck on problematic ones
        if len(available_recipes) > 10 and random.random() < 0.2:  # 20% chance to pick random
            next_recipe = random.choice(available_recipes[:10])  # From the first 10
            logger.info(f"Randomly selected from upcoming recipes")
        
        logger.info(f"Next recipe to upload: {next_recipe['dish_name']} (ID: {next_recipe['id']})")
        logger.info(f"Remaining recipes to upload: {len(available_recipes)}")
        return next_recipe
    
    def get_recipe_by_id(self, recipe_id):
        """Get a specific recipe by ID"""
        for recipe in self.recipes:
            if str(recipe.get('id')) == str(recipe_id):
                return recipe
        return None
    
    def _extract_file_id(self, drive_url):
        """Extract file ID from Google Drive URL"""
        if '/file/d/' in drive_url:
            file_id = drive_url.split('/file/d/')[1].split('/')[0]
            return file_id
        return None
    
    def download_video(self, recipe, max_retries=5):
        """Download video from Google Drive with advanced retry logic"""
        recipe_id = str(recipe['id'])
        
        # Update resume data
        self.resume_data[recipe_id] = {
            'status': 'downloading',
            'start_time': datetime.now().isoformat(),
            'dish_name': recipe['dish_name']
        }
        self._save_resume_data()
        
        try:
            # Check if we already have the video downloaded
            temp_video_path = os.path.join(self.temp_dir, f"original_{recipe_id}.mp4")
            if os.path.exists(temp_video_path):
                file_size = os.path.getsize(temp_video_path)
                if file_size > 1024*1024:  # If bigger than 1MB, assume it's valid
                    logger.info(f"Found existing download at {temp_video_path} ({file_size/1024/1024:.2f} MB)")
                    return temp_video_path
            
            file_id = self._extract_file_id(recipe['public_url'])
            if not file_id:
                raise ValueError(f"Invalid Google Drive URL: {recipe['public_url']}")
            
            # Try multiple times with smaller chunk size
            retry_count = 0
            chunk_size = 256 * 1024  # 256KB chunks for better reliability
            
            while retry_count < max_retries:
                try:
                    logger.info(f"Attempting download (try {retry_count+1}/{max_retries})...")
                    
                    request = self.drive_service.files().get_media(fileId=file_id)
                    video_file = io.BytesIO()
                    downloader = MediaIoBaseDownload(video_file, request, chunksize=chunk_size)
                    
                    # Download with progress tracking
                    done = False
                    while not done:
                        # Add exponential backoff within the download loop
                        try:
                            status, done = downloader.next_chunk()
                            logger.info(f"Download progress: {int(status.progress() * 100)}%")
                        except socket.timeout:
                            logger.warning(f"Chunk download timed out, retrying chunk...")
                            time.sleep(min(2 ** retry_count, 30))  # Exponential backoff
                            continue
                    
                    # Save the downloaded file to disk
                    with open(temp_video_path, 'wb') as f:
                        f.write(video_file.getvalue())
                    
                    file_size = os.path.getsize(temp_video_path)
                    logger.info(f"Successfully downloaded video to {temp_video_path} ({file_size/1024/1024:.2f} MB)")
                    return temp_video_path
                
                except socket.timeout:
                    retry_count += 1
                    if retry_count < max_retries:
                        logger.warning(f"Download timed out. Retry {retry_count}/{max_retries}...")
                        delay = min(2 ** retry_count, 60)  # Exponential backoff with max 60 sec
                        logger.info(f"Waiting {delay} seconds before retrying...")
                        time.sleep(delay)
                    else:
                        logger.error("Maximum retries reached for download")
                        raise
                except Exception as e:
                    logger.error(f"Download error: {str(e)}")
                    retry_count += 1
                    if retry_count < max_retries:
                        logger.warning(f"Retrying download {retry_count}/{max_retries}...")
                        time.sleep(10)
                    else:
                        raise
            
            raise Exception(f"Failed to download video after {max_retries} retries")
            
        except Exception as e:
            logger.error(f"Download failed: {str(e)}")
            raise
    
    def compress_video(self, input_path, recipe_id):
        """Compress video to reduce size using FFmpeg if available"""
        output_path = os.path.join(self.temp_dir, f"compressed_{recipe_id}.mp4")
        
        # Update resume data
        self.resume_data[str(recipe_id)]['status'] = 'compressing'
        self._save_resume_data()
        
        # Check if FFmpeg is installed
        try:
            # Check if the file is already compressed
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                if file_size > 1024*1024:  # If bigger than 1MB, assume it's valid
                    logger.info(f"Found existing compressed video at {output_path} ({file_size/1024/1024:.2f} MB)")
                    return output_path
            
            # Check if ffmpeg exists
            subprocess.run(['ffmpeg', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            
            # Get input file size
            input_size = os.path.getsize(input_path) / (1024 * 1024)  # MB
            logger.info(f"Original video size: {input_size:.2f} MB")
            
            # Skip compression for small videos
            if input_size < 10:  # If smaller than 10MB
                logger.info(f"Video already small ({input_size:.2f} MB). Skipping compression.")
                return input_path
            
            # Determine target bitrate based on input size
            # Aim for approximately 50% reduction for larger files
            target_size_mb = max(5, input_size * 0.5)  # Minimum 5MB, or 50% of original
            duration_cmd = subprocess.run(
                ['ffmpeg', '-i', input_path, '-f', 'null', '-'],
                stderr=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True
            )
            
            # Try to extract duration using regex
            duration_regex = re.search(r'Duration: (\d{2}):(\d{2}):(\d{2})', duration_cmd.stderr)
            
            # Default duration if we couldn't extract it
            duration_seconds = 120  # Assume 2 minutes if we can't determine
            
            if duration_regex:
                h, m, s = map(int, duration_regex.groups())
                duration_seconds = h * 3600 + m * 60 + s
            
            # Calculate target bitrate (bits per second)
            target_bitrate = int((target_size_mb * 8 * 1024 * 1024) / duration_seconds)
            
            logger.info(f"Compressing video to target size: {target_size_mb:.2f} MB (bitrate: {target_bitrate/1000:.0f} kbps)")
            
            # Run FFmpeg compression
            ffmpeg_cmd = [
                'ffmpeg', '-i', input_path,
                '-c:v', 'libx264', '-preset', 'fast',  # Use fast preset for quicker encoding
                '-b:v', f'{target_bitrate}',  # Target video bitrate
                '-maxrate', f'{int(target_bitrate * 1.5)}',  # Maximum bitrate
                '-bufsize', f'{int(target_bitrate * 2)}',  # Buffer size
                '-c:a', 'aac', '-b:a', '128k',  # Audio codec and bitrate
                '-y',  # Overwrite output file if it exists
                output_path
            ]
            
            logger.info(f"Running FFmpeg compression...")
            process = subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            if process.returncode != 0:
                logger.warning(f"FFmpeg compression failed: {process.stderr.decode()}")
                logger.info("Using original video file instead")
                return input_path
            
            # Check output file
            if os.path.exists(output_path):
                output_size = os.path.getsize(output_path) / (1024 * 1024)  # MB
                logger.info(f"Compressed video size: {output_size:.2f} MB (reduction: {(1 - output_size/input_size) * 100:.1f}%)")
                
                # If compression didn't reduce size significantly or made it larger, use original
                if output_size > input_size * 0.9:
                    logger.info("Compression didn't significantly reduce size. Using original file.")
                    return input_path
                
                return output_path
            else:
                logger.warning("Compression failed to create output file. Using original.")
                return input_path
                
        except (subprocess.SubprocessError, FileNotFoundError):
            logger.warning("FFmpeg not found or error during compression. Using original video file.")
            return input_path
        except Exception as e:
            logger.error(f"Error during video compression: {str(e)}")
            logger.info("Using original video file instead")
            return input_path
    
    def upload_to_youtube(self, video_path, recipe, max_retries=15):
        """Upload video to YouTube with enhanced retry and resume capability"""
        recipe_id = str(recipe['id'])
        
        # Update resume data
        self.resume_data[recipe_id]['status'] = 'uploading'
        self.resume_data[recipe_id]['video_path'] = video_path
        self._save_resume_data()
        
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
                try:
                    main_ingredient = ingredient.split(',')[0].split()[-1]
                    if main_ingredient and main_ingredient not in tags:
                        tags.append(main_ingredient)
                except (IndexError, ValueError):
                    pass  # Skip if there's any issue parsing ingredients
            
            # Limit tags to 500 characters total (YouTube limit)
            total_tags_length = sum(len(tag) for tag in tags)
            while total_tags_length > 490 and len(tags) > 5:
                tags.pop()  # Remove the last tag
                total_tags_length = sum(len(tag) for tag in tags)
            
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
            
            # Use very small chunk size for upload to better handle poor connections
            chunk_size = 256 * 1024  # 256KB chunks
            
            # Open the video file and get file size
            file_size = os.path.getsize(video_path)
            logger.info(f"Starting upload of {video_path} ({file_size/1024/1024:.2f} MB)")
            
            # Create MediaFileUpload object
            media = MediaFileUpload(
                video_path, 
                mimetype='video/mp4', 
                resumable=True,
                chunksize=chunk_size
            )
            
            # Create upload request
            upload_request = self.youtube_service.videos().insert(
                part=','.join(body.keys()),
                body=body,
                media_body=media
            )
            
            # Execute the upload with advanced retry logic
            response = None
            retry_count = 0
            last_progress = 0
            stalled_count = 0
            last_exception = None
            
            while response is None and retry_count < max_retries:
                try:
                    # Keep track of last exception for better error reporting
                    if last_exception:
                        logger.warning(f"Previous exception: {str(last_exception)}")
                        last_exception = None
                    
                    status, response = upload_request.next_chunk()
                    
                    if status:
                        current_progress = int(status.progress() * 100)
                        logger.info(f"Upload progress: {current_progress}%")
                        
                        # Check if upload is stalled (no progress)
                        if current_progress == last_progress:
                            stalled_count += 1
                            if stalled_count > 5:
                                logger.warning(f"Upload appears stalled at {current_progress}%. Retrying...")
                                raise socket.timeout("Upload stalled")
                        else:
                            stalled_count = 0
                            last_progress = current_progress
                
                except socket.timeout as e:
                    last_exception = e
                    retry_count += 1
                    delay = min(2 ** retry_count, 120)  # Exponential backoff with max 2 min
                    logger.warning(f"Upload timed out. Retry {retry_count}/{max_retries}...")
                    logger.info(f"Waiting {delay} seconds before retrying...")
                    time.sleep(delay)
                    if retry_count >= max_retries:
                        logger.error("Maximum retries reached for upload")
                        raise
                
                except googleapiclient.errors.HttpError as e:
                    last_exception = e
                    # Handle common Google API errors
                    if e.resp.status in [500, 502, 503, 504]:  # Server errors
                        retry_count += 1
                        delay = min(2 ** retry_count, 120)
                        logger.warning(f"Server error ({e.resp.status}). Retry {retry_count}/{max_retries}...")
                        time.sleep(delay)
                        if retry_count >= max_retries:
                            raise
                    else:
                        # For other HTTP errors, don't retry
                        logger.error(f"HTTP error: {e.resp.status} - {str(e)}")
                        raise
                
                except Exception as e:
                    last_exception = e
                    retry_count += 1
                    logger.warning(f"Upload error: {str(e)}. Retry {retry_count}/{max_retries}...")
                    time.sleep(min(2 ** retry_count, 120))
                    if retry_count >= max_retries:
                        raise
            
            if response:
                logger.info(f"Video uploaded successfully! Video ID: {response['id']}")
                
                # Mark recipe as used
                self.used_recipes.add(recipe_id)
                with open(self.used_recipes_file, 'w') as f:
                    json.dump(list(self.used_recipes), f)
                
                # Clear resume data for this recipe
                if recipe_id in self.resume_data:
                    del self.resume_data[recipe_id]
                    self._save_resume_data()
                
                # Return YouTube video URL
                return f"https://www.youtube.com/watch?v={response['id']}"
            else:
                raise Exception("Upload failed after maximum retries")
            
        except Exception as e:
            logger.error(f"Failed to upload to YouTube: {str(e)}")
            raise
    
    def _save_resume_data(self):
        """Save resume data to file"""
        try:
            with open(self.resume_data_file, 'w') as f:
                json.dump(self.resume_data, f)
        except Exception as e:
            logger.error(f"Failed to save resume data: {str(e)}")
    
    def cleanup(self, recipe_id):
        """Clean up temporary files"""
        try:
            original_path = os.path.join(self.temp_dir, f"original_{recipe_id}.mp4")
            compressed_path = os.path.join(self.temp_dir, f"compressed_{recipe_id}.mp4")
            
            for path in [original_path, compressed_path]:
                if os.path.exists(path):
                    os.remove(path)
                    logger.info(f"Removed temporary file: {path}")
        except Exception as e:
            logger.error(f"Failed to clean up files for recipe {recipe_id}: {str(e)}")
    
    def process_single_recipe(self, recipe_id=None):
        """Process a single recipe with enhanced error handling
        
        Args:
            recipe_id (str, optional): Specific recipe ID to process. If None, get next available.
        
        Returns:
            str: YouTube URL if successful, None otherwise
        """
        try:
            # Load recipes if not already loaded
            if not self.recipes:
                self.load_recipes()
            
            # Get the recipe to process
            recipe = None
            if recipe_id:
                recipe = self.get_recipe_by_id(recipe_id)
                if not recipe:
                    logger.error(f"Recipe with ID {recipe_id} not found")
                    return None
                
                # Check if it's already been uploaded
                if str(recipe['id']) in self.used_recipes:
                    logger.warning(f"Recipe {recipe['dish_name']} (ID: {recipe['id']}) has already been uploaded")
                    return None
            else:
                recipe = self.get_next_recipe()
                if not recipe:
                    logger.info("No more recipes to upload")
                    return None
            
            recipe_id = str(recipe['id'])
            logger.info(f"Processing recipe: {recipe['dish_name']} (ID: {recipe_id})")
            
            # Check for partial progress
            temp_video_path = None
            if recipe_id in self.resume_data:
                status = self.resume_data[recipe_id].get('status')
                logger.info(f"Found resume data with status: {status}")
                
                if status == 'uploading':
                    # Try to resume upload
                    video_path = self.resume_data[recipe_id].get('video_path')
                    if video_path and os.path.exists(video_path):
                        logger.info(f"Resuming upload for {recipe['dish_name']} with file {video_path}")
                        temp_video_path = video_path
            
            # If we don't have a video path from resume data, download it
            if not temp_video_path:
                # Download video
                original_video_path = self.download_video(recipe)
                
                # Compress video if possible
                temp_video_path = self.compress_video(original_video_path, recipe_id)
            
            # Upload to YouTube
            youtube_url = self.upload_to_youtube(temp_video_path, recipe)
            
            # Clean up (keep files for a while in case we need to retry)
            # Only clean up if upload was successful
            if youtube_url:
                self.cleanup(recipe_id)
            
            logger.info(f"Recipe {recipe['dish_name']} (ID: {recipe_id}) processed successfully")
            return youtube_url
            
        except Exception as e:
            logger.error(f"Failed to process recipe: {str(e)}")
            return None
    
    def get_status_report(self):
        """Generate a status report of uploaded and remaining recipes"""
        try:
            # Load recipes if not already loaded
            if not self.recipes:
                self.load_recipes()
            
            total_recipes = len(self.recipes)
            uploaded_count = len(self.used_recipes)
            remaining_count = total_recipes - uploaded_count
            
            # Calculate estimated completion time
            if uploaded_count > 0:
                # Assume each upload takes about 2 hours (worst case)
                estimated_hours = remaining_count * 2
                estimated_days = estimated_hours / 24
                completion_estimate = f"Estimated completion: {estimated_days:.1f} days at current rate"
            else:
                completion_estimate = "Unable to estimate completion time yet"
            
            logger.info(f"Status Report:")
            logger.info(f"  Total Recipes: {total_recipes}")
            logger.info(f"  Uploaded: {uploaded_count}")
            logger.info(f"  Remaining: {remaining_count}")
            logger.info(f"  {completion_estimate}")
            
            if remaining_count > 0:
                next_recipes = [r for r in self.recipes if str(r.get('id')) not in self.used_recipes]
                next_recipes.sort(key=lambda r: int(r.get('id', 0)))
                
                logger.info("Next 5 recipes to upload:")
                for i, recipe in enumerate(next_recipes[:5]):
                    logger.info(f"  {i+1}. ID {recipe['id']}: {recipe['dish_name']}")
            
            # Check for in-progress recipes
            if self.resume_data:
                logger.info("In-progress recipes:")
                for recipe_id, data in self.resume_data.items():
                    logger.info(f"  ID {recipe_id}: {data.get('dish_name')} - Status: {data.get('status')}")
            
            # Create a report file
            report_date = datetime.now().strftime('%Y-%m-%d')
            with open(f"recipe_status_{report_date}.txt", 'w') as f:
                f.write(f"Recipe Upload Status - {report_date}\n\n")
                f.write(f"Total Recipes: {total_recipes}\n")
                f.write(f"Uploaded: {uploaded_count}\n")
                f.write(f"Remaining: {remaining_count}\n")
                f.write(f"{completion_estimate}\n\n")
                
                # In-progress recipes
                if self.resume_data:
                    f.write("In-progress recipes:\n")
                    for recipe_id, data in self.resume_data.items():
                        start_time = data.get('start_time', 'unknown')
                        if isinstance(start_time, str) and 'T' in start_time:
                            start_time = start_time.replace('T', ' ')
                        f.write(f"ID {recipe_id}: {data.get('dish_name')} - Status: {data.get('status')} (Started: {start_time})\n")
                    f.write("\n")
                
                if remaining_count > 0:
                    f.write("Next 10 recipes to upload:\n")
                    for i, recipe in enumerate(next_recipes[:10]):
                        f.write(f"{i+1}. ID {recipe['id']}: {recipe['dish_name']}\n")
                    
                    f.write("\nAll remaining recipes:\n")
                    for recipe in next_recipes:
                        f.write(f"ID {recipe['id']}: {recipe['dish_name']}\n")
            
            logger.info(f"Status report written to recipe_status_{report_date}.txt")
            
        except Exception as e:
            logger.error(f"Failed to generate status report: {str(e)}")


def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Upload recipes to YouTube with robust error handling')
    parser.add_argument('--json', default='paste.txt', help='Path to the recipe JSON file')
    parser.add_argument('--credentials', default='credentials.json', help='Path to the Google API credentials file')
    parser.add_argument('--id', help='Specific recipe ID to upload (optional)')
    parser.add_argument('--status', action='store_true', help='Generate a status report only, no upload')
    parser.add_argument('--cleanup', action='store_true', help='Clean up temporary files from previous runs')
    args = parser.parse_args()
    
    # Create uploader
    uploader = RobustUploader(args.json, args.credentials)
    
    # Authenticate with Google
    uploader.authenticate()
    
    if args.status:
        # Generate status report only
        uploader.get_status_report()
    elif args.cleanup:
        # Clean up temp directory
        import shutil
        if os.path.exists(uploader.temp_dir):
            logger.info(f"Cleaning up temporary directory: {uploader.temp_dir}")
            shutil.rmtree(uploader.temp_dir)
            os.makedirs(uploader.temp_dir)
        # Clear resume data
        uploader.resume_data = {}
        uploader._save_resume_data()
        logger.info("Cleanup complete")
    else:
        # Process a single recipe
        youtube_url = uploader.process_single_recipe(args.id)
        
        if youtube_url:
            logger.info(f"Video uploaded successfully: {youtube_url}")
        else:
            logger.warning("No video was uploaded")

if __name__ == "__main__":
    main()