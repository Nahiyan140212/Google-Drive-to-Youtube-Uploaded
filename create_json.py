import json

def merge_json_files(recipes_file, youtube_links_file, output_file):
    # Load recipes data
    with open(recipes_file, 'r', encoding='utf-8') as f:
        recipes_data = json.load(f)
    
    # Load YouTube links data
    with open(youtube_links_file, 'r', encoding='utf-8') as f:
        youtube_links_data = json.load(f)
    
    # Create a dictionary of YouTube links with recipe_id as the key
    youtube_links_dict = {link['recipe_id']: link['youtube_link'] for link in youtube_links_data['youtube_links']}
    
    # Merge the data
    for recipe in recipes_data['recipes']:
        recipe_id = recipe['id']
        # Check if the recipe_id exists in youtube_links_dict
        if recipe_id in youtube_links_dict:
            # If the recipe already has a youtube_link field, update it
            # Otherwise, add the youtube_link field
            recipe['youtube_link'] = youtube_links_dict[recipe_id]
    
    # Save the merged data to a new file
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(recipes_data, f, indent=4, ensure_ascii=False)
    
    print(f"Merged data saved to {output_file}")

# File paths
recipes_file = 'recipes.json'
youtube_links_file = 'youtube_links.json'
output_file = 'merged_recipes.json'

# Merge the files
merge_json_files(recipes_file, youtube_links_file, output_file)