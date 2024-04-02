from functools import wraps
from flask import Flask, abort, jsonify, redirect, render_template, flash, request, send_from_directory, session, make_response
from flask_wtf import FlaskForm
from flask_wtf.csrf import CSRFProtect
from wtforms import FileField, HiddenField, SubmitField
from werkzeug.utils import secure_filename
import os
from wtforms.validators import InputRequired
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity, set_access_cookies, set_refresh_cookies
from OpenSSL import SSL

class UploadFileForm(FlaskForm):
    file = FileField("File", validators=[InputRequired()])
    submit = SubmitField("Upload File")
    
app = Flask(__name__)
SECRET_KEY = os.urandom(32)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['JWT_SECRET_KEY'] = 'supersecretkey'
app.config['UPLOAD_FOLDER'] = 'static/files'
app.config['JWT_TOKEN_LOCATION'] = ['cookies']
app.config['JWT_COOKIE_CSRF_PROTECT'] = False
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif'}
CERT_FILE = "utils/keys/certificate.pem" 
KEY_FILE = "utils/keys/key.pem" 

# context = SSL.Context(SSL.PROTOCOL_TLSv1_2) 
# context.load_cert_chain(CERT_FILE, KEY_FILE) 

jwt = JWTManager(app)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/login', methods=['POST'])
def login():

    if not request.is_json:
        return jsonify({"msg": "Missing JSON in request"}), 400

    username = request.json.get('username', None)
    password = request.json.get('password', None)
    if not username or not password:
        return jsonify({"msg": "Missing username or password"}), 400

    # Normally, you'd verify the username and password here.
    # Just a dummy check here for illustration.
    if username != 'test' or password != 'test':
        return jsonify({"msg": "Bad username or password"}), 401

    access_token = create_access_token(identity=username)
    res = make_response(jsonify(access_token=access_token))
    set_access_cookies(res, access_token)
    return res

@app.route('/')
def home():
    if not session.get('logged_in'):
        return render_template('login.html')
    else:
        return 'logged in currently'

@app.route('/home', methods = ['GET', 'POST'])
@jwt_required()
def file_browser():
    form = UploadFileForm()
    
    if form.validate_on_submit():
        file = form.file.data # First grab the file
        file.save(os.path.join(os.path.abspath(os.path.dirname(__file__)),app.config['UPLOAD_FOLDER'],secure_filename(file.filename))) # Then save the file
        flash('File uploaded successfully!', 'success')
    files = os.listdir(app.config['UPLOAD_FOLDER'])   
    return render_template('upload.html', form=form, files = files)


@app.route('/uploads/<filename>')
@jwt_required()
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

@app.route('/delete/<filename>', methods=['POST'])
@jwt_required()
def delete_file(filename):
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    return redirect('/home')


@jwt.unauthorized_loader
def missing_token_callback(error):
    return (
        jsonify(
            {
                "message": "Request doesnt contain valid token",
                "error": "authorization_header",
            }
        ),
        401,
    )


if __name__ == '__main__':
    app.run(debug=True)