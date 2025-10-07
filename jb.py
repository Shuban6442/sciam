from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from flask_cors import CORS

app = Flask(__name__)
app.config['SECRET_KEY'] = 'whiteboard-test-key-123'

# Enable CORS and SocketIO
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True)

# Simple session storage
sessions = {}

@app.route('/')
def index():
    return render_template('whiteboard.html')

@socketio.on('connect')
def handle_connect():
    print(f"🔗 Client connected: {request.sid}")
    emit('connected', {'message': 'Connected to server'})

@socketio.on('disconnect')
def handle_disconnect():
    print(f"🔗 Client disconnected: {request.sid}")

@socketio.on('create_session')
def handle_create_session(data):
    print(f"📝 Create session: {data}")
    
    session_id = data.get('session_id')
    user_name = data.get('user_name', 'Anonymous')
    
    if not session_id:
        emit('session_error', {'message': 'Session ID is required'})
        return
    
    if session_id in sessions:
        emit('session_error', {'message': 'Session already exists'})
        return
    
    # Create session
    sessions[session_id] = {
        'users': [{'user_id': request.sid, 'user_name': user_name}]
    }
    
    print(f"✅ Session created: {session_id} with user: {user_name}")
    emit('session_created', {
        'session_id': session_id,
        'user_name': user_name
    })

@socketio.on('join_session')
def handle_join_session(data):
    print(f"📝 Join session: {data}")
    
    session_id = data.get('session_id')
    user_name = data.get('user_name', 'Anonymous')
    
    if not session_id:
        emit('session_error', {'message': 'Session ID is required'})
        return
    
    if session_id not in sessions:
        emit('session_error', {'message': 'Session not found'})
        return
    
    # Add user to session
    sessions[session_id]['users'].append({
        'user_id': request.sid,
        'user_name': user_name
    })
    
    print(f"✅ User joined: {user_name} to session: {session_id}")
    emit('session_joined', {
        'session_id': session_id,
        'user_name': user_name
    })
    
    # Notify others
    emit('user_joined', {
        'user_id': request.sid,
        'user_name': user_name
    }, broadcast=True)

@socketio.on('leave_session')
def handle_leave_session(data):
    print(f"📝 Leave session: {data}")
    # Simple implementation - just notify
    emit('session_left', {'message': 'Left session'})

if __name__ == '__main__':
    print("🚀 Starting Whiteboard Debug Server...")
    print("📍 URL: http://localhost:5001")
    print("🔧 Debug mode enabled")
    socketio.run(app, host='0.0.0.0', port=5001, debug=True)