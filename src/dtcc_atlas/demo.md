# Before installing and using make sure you add your credentials and defualt data directory at the parameters.py file  

# Download the demo on server side
git clone dtcc-data

# Define stored input data, e.g. Tile_01,Tile_02 directories with .gpgk file in each
To do that you must move the GPKG Tiles in the dtcc-atlas/server_data folder (The script takes as input all the GPKG files in the current directory)

# Read those two Tiles and create an catalog.json
First you need to change directory to the dtcc atlas folder (cd dtcc-data/utils/dtcc-atlas)
run tiling.py (This create the catalog.json which is essentialy the atlas for the gpkg in the server side as well as file_to_coords which connects a tile filename with the coordinates)
Beware that the tiles must be named and have bounding boxes as to landmateriet bounding box tiles for sweden. If thats not the case the script will not work

# Download the demo on client side
git clone dtcc-data on client side

# Initialize client side (I guess we need a local catalog.json?)
This is the "tester" side. It can work without providing an atlas, as it will create its own during the process. You can change the bounding box in the checker file:line 17

# Request data for a specific bounding box
Make sure you are in the dtcc-data directory. You can change the bounding box accordingly as previously mentioned and get partial data full data(if everythign is missing)
