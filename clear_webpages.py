from pathlib import Path
import shutil

def empty_directory(dir_path):
    path = Path(dir_path)
    
    # Iterate through all items in the directory
    for item in path.iterdir():
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item) # Delete subdirectories and their contents
        else:
            item.unlink() # Delete files or symbolic links

# Example usage:
empty_directory('webpages')
