import threading
import webbrowser
from flask import Flask, render_template, request, jsonify, send_file
from shapely import box
import tarfile
import os
import sys
import json
import time
from pyproj import Proj, transform
# import pyautogui

base_url = "http://129.16.69.36:54321"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from atlas import prototype

findFiles = prototype.findFiles

app = Flask(__name__)
start_time = time.time()
laz_directory = "../../../../../65_3" #DATA LOCATION HERE
zip_folder = "zipped_data"

try:
    with open("atlas_lidar.json", "r") as f1:
        laz_data = json.load(f1)
except:
    print("Missing Laz atlas. Trying to start without bygg atlas")  
    laz_data = None      

try:
    with open("atlas_bygg.json", "r") as f2:
        bygg_data = json.load(f2)
except:
    print("Missing bygg atlas. Trying to start without bygg atlas.")
    bygg_data = None

try:
    with open("atlas_vl.json", "r") as f3:
        vl_data = json.load(f3)
except:
    print("Missing bygg atlas. Trying to start without bygg atlas.")
    vl_data = None

if not laz_data and not bygg_data and not vl_data:
    print("All atlas files are missing. The server cannot serve data so its terminated")
    exit()

if not os.path.exists(zip_folder):
        os.mkdir(zip_folder)

def create_tarball(output_filename, directory, file_list, extra_file = None):
    """
    Create a tar.gz archive of specific files within a directory.

    Args:
    output_filename (str): The path where the tar.gz file will be saved.
    directory (str): The directory containing the files to be archived.
    file_list (list): A list of filenames to be included in the archive.
    """
    with tarfile.open(output_filename, "w:gz") as tar:
        for filename in file_list:
            file_path = os.path.join(directory, filename)
            if os.path.exists(file_path):
                tar.add(file_path, arcname=filename)
            else:
                print(f"File not found: {file_path}")
        if extra_file:        
            tar.add(extra_file)
    try:        
        os.remove(extra_file)
    except:
        pass

# Store coordinates globally
coordinates = None

# Initialize projections for WGS84 and SWEREF 99 TM
wgs84 = Proj(proj='latlong', datum='WGS84')
sweref99tm = Proj(init='epsg:3006')

# HTML content for the map page

@app.route('/open_map', methods=['GET'])
def open_map():
    """API endpoint to open the map."""
    # Reset coordinates
    global coordinates
    coordinates = None
    
    # Open the map in a browser
    threading.Thread(target=open_browser).start()
    
    return jsonify({'status': 'Map opened, please submit coordinates.'})

@app.route('/map', methods=['GET'])
def map_page():
    """Serve the map to the user."""
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
def submit_coordinates():
    global coordinates
    data = request.json
    coordinates = transform_coordinates(data['topLeft'], data['bottomRight'])
    print("Transformed coordinates:", coordinates)
    
    # Gracefully shut down the server and close the browser
    threading.Thread(target=shutdown_server_and_close_browser).start()
    return jsonify({'status': 'success'})

@app.route('/get_coordinates', methods=['GET'])
def get_coordinates():
    """API endpoint to retrieve the submitted coordinates."""
    global coordinates
    if coordinates is not None:
        return jsonify({'coordinates': coordinates})
    else:
        return jsonify({'error': 'No coordinates have been submitted yet.'}), 400

def transform_coordinates(top_left, bottom_right):
    # Transform coordinates from WGS84 to SWEREF 99 TM
    top_left_x, top_left_y = transform(wgs84, sweref99tm, top_left['lng'], top_left['lat'])
    bottom_right_x, bottom_right_y = transform(wgs84, sweref99tm, bottom_right['lng'], bottom_right['lat'])
    return {
        'topLeft': {'x': top_left_x, 'y': top_left_y},
        'bottomRight': {'x': bottom_right_x, 'y': bottom_right_y}
    }

def shutdown_server_and_close_browser():
    time.sleep(1)
    # pyautogui.hotkey('ctrl', 'w')  # Close the current tab

def open_browser():
    webbrowser.open(f'{base_url}/map')

@app.route('/health',methods=['GET'])
def health():
    current_time = time.time()
    uptime_seconds = current_time - start_time
    uptime = {'uptime_seconds': uptime_seconds}
    return jsonify(uptime)

@app.route('/api/post/boundingbox', methods=['POST'])
def process_bounding_box():
    # Expecting JSON data with four points
    data = request.get_json()
    
    # Validate input to make sure it contains four points
    if not data or 'points' not in data or len(data['points']) != 4:
        return jsonify({'error': 'Invalid data, please provide exactly four points'}), 400
    type = data["type"]
    # Extract points
    points = data['points']
    selected_area = box(points[0], points[1], points[2], points[3])
    serverfiles = []
    if type == "laz" and laz_data:
        serverfiles = findFiles(laz_data, selected_area)
    elif type == "bygg" and bygg_data:
        serverfiles = findFiles(bygg_data, selected_area)
    elif type == "vl":
        serverfiles = findFiles(vl_data, selected_area)
    
    return jsonify({
        'received_points': serverfiles
    })
    

@app.route('/download-bygg', methods=['POST', 'GET']) 
def download_bygg_files():
    try:
        os.remove("zipped_data/myfiles.tar.gz")
    except:
        pass
    with open("file_to_coords_bygg.json", "r") as ftc:
        data = json.load(ftc)
    data_list = request.get_json(())["filenames"]
    missing_files_coords = {}
    for file in data_list:
        print(data[file])
        missing_files_coords[file] = data[file]
    with open("missing_coords.json", "w") as coords:
        json.dump(missing_files_coords, coords, indent=4)
    # with tarfile.open('zipped_data/myfiles.tar.gz', "w:gz") as tar:
    #     tar.add("missing_coords.json")
    create_tarball("zipped_data/myfiles.tar.gz", "tiled_data_bygg", data_list, "missing_coords.json")
    return send_file('zipped_data/myfiles.tar.gz', as_attachment=True, download_name='example.tar')


@app.route('/download-vl', methods=['POST', 'GET']) 
def download_vl_files():
    try:
        os.remove("zipped_data/myfiles.tar.gz")
    except:
        pass
    with open("file_to_coords_vl.json", "r") as ftc:
        data = json.load(ftc)
    data_list = request.get_json(())["filenames"]
    missing_files_coords = {}
    for file in data_list:
        print(data[file])
        missing_files_coords[file] = data[file]
    with open("missing_coords.json", "w") as coords:
        json.dump(missing_files_coords, coords, indent=4)
    # with tarfile.open('zipped_data/myfiles.tar.gz', "w:gz") as tar:
    #     tar.add("missing_coords.json")
    create_tarball("zipped_data/myfiles.tar.gz", "tiled_data_vl", data_list, "missing_coords.json")
    return send_file('zipped_data/myfiles.tar.gz', as_attachment=True, download_name='example.tar')



@app.route('/download-laz', methods=['GET'])
def download_laz_files():
    data_list = request.get_json(())
    if os.path.exists("zipped_data/myfiles.tar.gz"):
        os.remove("zipped_data/myfiles.tar.gz")
    # create_tarball("zipped_data/myfiles.tar.gz", "../../../atlas_small", data_list["filenames"]) #laz files
    create_tarball("zipped_data/myfiles.tar.gz", laz_directory, data_list["filenames"])
    return send_file('zipped_data/myfiles.tar.gz', as_attachment=True, download_name='example.tar')

if __name__ == '__main__':
    app.run(host = "0.0.0.0" ,debug=True, port=54321)