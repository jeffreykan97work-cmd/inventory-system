"""
PythonAnywhere WSGI config for DMA Inventory System.
Upload all files to /home/{username}/inventory-system/
Then point your PythonAnywhere web app to this file.
"""
import sys, os

# Add project dir to path
project_dir = os.path.dirname(__file__)
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

# Set DB path to a persistent location
os.environ["DB_PATH"] = os.path.join(project_dir, "inventory.db")

from server import app as application
