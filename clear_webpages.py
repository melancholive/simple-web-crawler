from pathlib import Path
import shutil

def empty_directory(dir_path):
    path = Path(dir_path)
    
    # iterate through all items in the directory
    for item in path.iterdir():
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item) # delete subdirectories and their contents
        else:
            item.unlink() # delete files or symbolic links

empty_directory('webpages')
