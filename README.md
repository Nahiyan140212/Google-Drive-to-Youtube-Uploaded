# Youtube-Video-Uploaded-Project
# Recipe Video Uploader

A system for automatically downloading recipe videos from Google Drive and uploading them to YouTube.

## Overview

This project consists of two main scripts:
- `recipe_agent.py`: Batch uploader that attempts to upload multiple videos in sequence
- `sequential_uploader.py`: Single recipe uploader designed for more reliable operation over poor connections

## Requirements

- Python 3.6+
- Google Cloud project with YouTube and Drive APIs enabled
- OAuth 2.0 credentials
- JSON file containing recipe data

## Installation

1. Clone or download this repository
2. Install required dependencies:
   ```bash
   pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
   ```
3. Set up your Google Cloud project:
   - Create a project at [console.cloud.google.com](https://console.cloud.google.com)
   - Enable YouTube Data API v3 and Google Drive API
   - Create OAuth credentials (Desktop app type)
   - Download credentials as `credentials.json`

## Configuration

1. Place your recipe JSON file in the project directory
2. Place your `credentials.json` file in the project directory
3. Update file paths in the scripts if necessary

## Recipe JSON Format

The JSON file should have the following structure:
```json
{
  "recipes": [
    {
      "id": 51,
      "dish_name": "Creamy Spinach Salmon",
      "dish_type": "Main",
      "taste_category": "Savory",
      "ingredients": ["ingredient1", "ingredient2", ...],
      "instructions": ["step1", "step2", ...],
      "prep_time": "10 minutes",
      "cook_time": "15 minutes",
      "yield": "2 servings",
      "public_url": "https://drive.google.com/file/d/..."
    },
    ...
  ]
}
```

## Usage

### Sequential Uploader (Recommended)

This script uploads one recipe at a time, perfect for running periodically (e.g., every 6 hours) with more reliable operation on slow connections.

#### Basic Usage
```bash
python sequential_uploader.py
```

This will:
- Find the next recipe that hasn't been uploaded yet
- Download the video from Google Drive
- Upload it to YouTube with proper metadata
- Mark the recipe as completed

#### Upload a Specific Recipe
```bash
python sequential_uploader.py --id 54
```

#### Generate Status Report
```bash
python sequential_uploader.py --status
```

#### Additional Options
```bash
python sequential_uploader.py --json path/to/recipes.json --credentials path/to/credentials.json
```

### Batch Uploader

The original script attempts to upload multiple videos in one run.

```bash
python recipe_agent.py
```

## Upload Tracking

Both scripts use a file called `used_recipes.json` to track which recipes have been uploaded. This ensures:

1. No duplicate uploads
2. Progress is maintained between runs
3. You can stop and restart the process at any time

## Customization

You can adjust the following parameters in the scripts:
- `MAX_UPLOADS`: Number of videos to process in batch mode
- Socket timeout values
- Retry counts and delays
- Chunk sizes for download/upload

## Error Handling

The scripts include robust error handling for:
- Network timeouts
- Authentication issues
- File parsing problems
- API errors

Detailed logs are written to:
- `recipe_agent.log` (batch uploader)
- `sequential_uploader.log` (sequential uploader)

## Recommended Workflow

1. Run `sequential_uploader.py` every 6 hours to upload one video at a time
2. Periodically check the status with `sequential_uploader.py --status`
3. If specific recipes fail repeatedly, try uploading them individually with the `--id` option
4. Monitor the log files for any persistent issues

## Troubleshooting

- **Authentication Errors**: Delete `token.json` and re-run the script
- **Timeout Issues**: Try a more stable internet connection
- **File Not Found**: Check your file paths
- **API Quota Exceeded**: Wait 24 hours or request quota increase
- **JSON Parsing Errors**: Validate your JSON file

## License

This project is available for personal use.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.