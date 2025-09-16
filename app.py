from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from jwt import ExpiredSignatureError, InvalidTokenError
from datetime import datetime, timedelta, UTC
from functools import wraps
import ephem
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import base64
import os
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
CORS(app)

base_dir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(base_dir, 'moonphase.db')

app.config.update(
    SECRET_KEY='dev-key-123',
    SQLALCHEMY_DATABASE_URI=f'sqlite:///{db_path}',
    SQLALCHEMY_TRACK_MODIFICATIONS=False
)

db = SQLAlchemy(app)
class User(db.Model):
    id            = db.Column(db.Integer,   primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    password      = db.Column(db.String(200), nullable=False)
    created_at    = db.Column(db.DateTime,   default=lambda: datetime.now(UTC))
    last_login    = db.Column(db.DateTime)
    calculations  = db.Column(db.Integer,    default=0)


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        parts = auth.split()
        if len(parts) != 2 or parts[0].lower() != 'bearer':
            return jsonify({'message': 'Invalid or missing Authorization header'}), 401

        token = parts[1]
        try:
            payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=["HS256"])
            user = User.query.filter_by(username=payload['username']).first()
            if not user:
                return jsonify({'message': 'User not found'}), 401
            return f(user, *args, **kwargs)

        except ExpiredSignatureError:
            return jsonify({'message': 'Token has expired'}), 401
        except (InvalidTokenError, Exception):
            return jsonify({'message': 'Invalid token'}), 401

    return decorated


SYNODIC_MONTH = 29.530588853

def get_phase_name_from_age(age_days: float) -> str:
    """Map moon age (days since new moon) to one of eight phase names."""
    fm = SYNODIC_MONTH
    if   age_days < fm * 1/8: return "New Moon"
    elif age_days < fm * 2/8: return "Waxing Crescent"
    elif age_days < fm * 3/8: return "First Quarter"
    elif age_days < fm * 4/8: return "Waxing Gibbous"
    elif age_days < fm * 5/8: return "Full Moon"
    elif age_days < fm * 6/8: return "Waning Gibbous"
    elif age_days < fm * 7/8: return "Last Quarter"
    else:                     return "Waning Crescent"


@app.route('/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    usern = data.get('username', '').strip()
    pwd   = data.get('password', '')

    if not usern or not pwd:
        return jsonify({'message': 'Missing username or password'}), 400
    if User.query.filter_by(username=usern).first():
        return jsonify({'message': 'Username already exists'}), 400

    usr = User(username=usern, password=generate_password_hash(pwd))
    db.session.add(usr)
    db.session.commit()
    return jsonify({'message': 'Registration successful'}), 201

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    usern = data.get('username', '').strip()
    pwd   = data.get('password', '')

    if not usern or not pwd:
        return jsonify({'message': 'Missing username or password'}), 400

    usr = User.query.filter_by(username=usern).first()
    if not usr or not check_password_hash(usr.password, pwd):
        return jsonify({'message': 'Invalid credentials'}), 401

    usr.last_login = datetime.now(UTC)
    db.session.commit()

    token = jwt.encode({
        'username': usr.username,
        'exp': datetime.utcnow() + timedelta(hours=24)
    }, app.config['SECRET_KEY'], algorithm="HS256")

    return jsonify({
        'token': token,
        'username': usr.username,
        'calculations': usr.calculations,
        'last_login': usr.last_login.isoformat()
    })

@app.route('/get-moon-phase', methods=['POST'])
@token_required
def get_moon_phase(current_user: User):
    data = request.get_json() or {}
    date_str = data.get('date', '')
    if not date_str:
        return jsonify({'message': 'Date is required'}), 400

    # 1) Parse to ephem.Date
    try:
        e_date = ephem.Date(date_str)
    except:
        return jsonify({'message': 'Invalid date format; use YYYY-MM-DD'}), 400

    # 2) Compute illumination
    m = ephem.Moon()
    m.compute(e_date)
    illumination = float(m.phase)  # percent illuminated

    # 3) Compute age (days since last new moon)
    prev_new = ephem.previous_new_moon(e_date)
    age_days = float(e_date - prev_new)

    # 4) Draw moon image
    plt.ioff()
    fig, ax = plt.subplots(figsize=(6,6))
    ax.set_aspect('equal'); ax.axis('off')
    ax.add_patch(plt.Circle((0.5,0.5), 0.4, color='white'))

    # shadow offset
    offset = (1 - 2*illumination/100)*0.4
    # waxing vs waning: illumination < 50 ⇒ waxing (shadow on left), else waning (shadow on right)
    shadow_x = 0.5 + offset if illumination <= 50 else 0.5 - offset
    ax.add_patch(plt.Circle((shadow_x, 0.5), 0.4, color='black'))

    ax.set_xlim(0,1); ax.set_ylim(0,1)
    fig.patch.set_facecolor('black')
    buf = io.BytesIO()
    plt.savefig(buf, format='png', facecolor='black', bbox_inches='tight', dpi=100)
    buf.seek(0); plt.close('all')

    img_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')

    # 5) Update user count
    current_user.calculations += 1
    db.session.commit()

    return jsonify({
        'phase_name': get_phase_name_from_age(age_days),
        'illumination': round(illumination, 2),
        'moon_image': img_b64,
        'calculations': current_user.calculations
    })

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='127.0.0.1', port=5000)