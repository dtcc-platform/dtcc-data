from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/api/post/boundingbox', methods=['POST'])
def process_bounding_box():
    # Expecting JSON data with four points
    data = request.get_json()
    
    # Validate input to make sure it contains four points
    if not data or 'points' not in data or len(data['points']) != 4:
        return jsonify({'error': 'Invalid data, please provide exactly four points'}), 400
    
    # Extract points
    points = data['points']
    # Themis adds logic for points to lidar filenames here


    # Here you could add any processing you want on the points
    # For now, let's just return them as they are
    
    return jsonify({
        'received_points': points
    })

if __name__ == '__main__':
    app.run(debug=True)