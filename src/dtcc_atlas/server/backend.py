from flask import Flask, request, jsonify, send_file
from shapely import box
import tarfile
import os
import sys
import json
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from atlas import prototype

findFiles = prototype.findFiles

app = Flask(__name__)
start_time = time.time()
laz_directory = "../../../65_3" #DATA LOCATION HERE
zip_folder = "zipped_data"
try:
    with open("atlas_lidar.json", "r") as f1:
        laz_data = json.load(f1)
except:
    print("Missing Laz atlas. Trying to start without bygg atlas")  
    laz_data = None      

try:
    with open("atlas_bygg.json", "r") as f2:
        gpkg_data = json.load(f2)
except:
    print("Missing bygg atlas. Trying to start without bygg atlas.")
    bygg_data = None

try:
    with open("atlas_vl.json", "r") as f2:
        gpkg_data = json.load(f2)
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
    elif type == "gpkg" and gpkg_data:
        serverfiles = findFiles(gpkg_data, selected_area)
    
    return jsonify({
        'received_points': serverfiles
    })
    

@app.route('/download-bygg', methods=['POST', 'GET']) 
def download_gpkg_files():
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
def download_gpkg_files():
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