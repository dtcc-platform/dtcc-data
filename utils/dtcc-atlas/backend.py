from flask import Flask, request, jsonify, send_file
from prototype import findFiles
from shapely import box
import tarfile
import os
import json
app = Flask(__name__)


def create_tarball(output_filename, directory, file_list, extra_file):
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
        tar.add(extra_file)

@app.route('/api/post/boundingbox', methods=['POST'])
def process_bounding_box():
    # Expecting JSON data with four points
    data = request.get_json()
    
    # Validate input to make sure it contains four points
    if not data or 'points' not in data or len(data['points']) != 4:
        return jsonify({'error': 'Invalid data, please provide exactly four points'}), 400
    
    # Extract points
    points = data['points']
    selected_area = box(points[0], points[1], points[2], points[3])
    serverfiles = findFiles('catalog.json', selected_area)


    # Here you could add any processing you want on the points
    # For now, let's just return them as they are
    
    return jsonify({
        'received_points': serverfiles
    })
    

@app.route('/download-gpkg', methods=['POST', 'GET']) 
def download_gpkg_files():
    try:
        os.remove("zipped_data/myfiles.tar.gz")
    except:
        pass
    with open("file_to_coords.json", "r") as ftc:
        data = json.load(ftc)
    data_list = request.get_json(())["filenames"]
    missing_files_coords = {}
    print(data_list)
    for file in data_list:
        print(data[file])
        missing_files_coords[file] = data[file]
    with open("missing_coords.json", "w") as coords:
        json.dump(missing_files_coords, coords, indent=4)
    # with tarfile.open('zipped_data/myfiles.tar.gz', "w:gz") as tar:
    #     tar.add("missing_coords.json")
    create_tarball("zipped_data/myfiles.tar.gz", "tiles_output", data_list, "missing_coords.json")
    return send_file('zipped_data/myfiles.tar.gz', as_attachment=True, download_name='example.tar')



@app.route('/download-laz', methods=['POST', 'GET'])
def download_laz_files():
    data_list = request.get_json(())
    if os.path.exists("zipped_data/myfiles.tar.gz"):
        os.remove("zipped_data/myfiles.tar.gz")
    # create_tarball("zipped_data/myfiles.tar.gz", "../../../atlas_small", data_list["filenames"]) #laz files
    create_tarball("zipped_data/myfiles.tar.gz", "tiles_output", data_list["filenames"])
    return send_file('zipped_data/myfiles.tar.gz', as_attachment=True, download_name='example.tar')

if __name__ == '__main__':
    app.run(debug=True)