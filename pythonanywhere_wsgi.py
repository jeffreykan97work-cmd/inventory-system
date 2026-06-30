"""
PythonAnywhere WSGI config for DMA Inventory System (Flask version).
Upload all files to /home/dmawarehouse/inventory-system/
"""
import sys, os

project_dir = os.path.dirname(__file__)
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

os.environ["DB_PATH"] = os.path.join(project_dir, "inventory.db")

from flask_app import app as application
