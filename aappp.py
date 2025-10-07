import sys
import uuid
import tempfile
import subprocess
import threading
import time
import select
import os
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room
import queue

app = Flask(__name__)
app.config['SECRET_KEY'] = 'siren-secret-key-123'

socketio = SocketIO(app, 
                   cors_allowed_origins="*",
                   async_mode='threading')

# Store sessions in memory
sessions = {}
# Store running processes and input queues
running_processes = {}
input_queues = {}
process_needs_input = {}  # Track which processes actually need input

@app.route("/")
def index():
    return render_template("home.html")

@app.route("/create_session", methods=["POST"])
def create_session():
    session_id = str(uuid.uuid4())[:8]
    sessions[session_id] = {
        "content": "# Welcome to SIREN Collaborative Editor\n# Start coding in Python...\nprint('Hello, World!')",
        "participants": {},
        "host_id": None,
        "writer_id": None,
        "chat_messages": []
    }
    print(f"🎉 New session created: {session_id}")
    return jsonify({"session_id": session_id})

@app.route("/editor/<session_id>")
def editor(session_id):
    if session_id not in sessions:
        return "Session not found", 404
    return render_template("neweditor.html", session_id=session_id)

@app.route("/run_code", methods=["POST"])
def run_code():
    data = request.get_json()
    code = data.get("code", "")
    session_id = data.get("session_id")
    user_input = data.get("user_input", "")
    process_id = data.get("process_id")

    # If this is providing input to an existing process
    if process_id and user_input:
        if process_id in input_queues:
            input_queues[process_id].put(user_input + "\n")
            return jsonify({"status": "input_sent", "message": "Input sent to process"})
        else:
            return jsonify({"status": "error", "message": "Process not found or completed"})

    try:
        # Check if code contains input statements
        code_needs_input = "input(" in code
        
        # Create a unique process ID for this execution
        process_id = str(uuid.uuid4())
        
        # Create input queue for this process
        input_queues[process_id] = queue.Queue()
        process_needs_input[process_id] = code_needs_input
        
        # Run the code in a separate thread to handle input
        thread = threading.Thread(
            target=run_code_with_input,
            args=(code, process_id, session_id, code_needs_input)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            "status": "started", 
            "process_id": process_id,
            "needs_input": code_needs_input,
            "message": "Code execution started successfully"
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error starting execution: {str(e)}"})

def run_code_with_input(code, process_id, session_id, code_needs_input):
    """Run Python code in a separate thread with smart input handling"""
    process = None
    temp_filename = None
    
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py", mode='w', encoding='utf-8') as tmp:
            tmp.write(code)
            tmp.flush()
            temp_filename = tmp.name

        # Create a subprocess with pipes for stdin/stdout/stderr
        process = subprocess.Popen(
            [sys.executable, temp_filename],
            stdin=subprocess.PIPE if code_needs_input else None,  # Only provide stdin if needed
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        running_processes[process_id] = process
        
        # Send initial confirmation
        socketio.emit("code_output", {
            "process_id": process_id,
            "output": "🚀 Code execution started...\n",
            "type": "system"
        }, room=session_id)
        
        # If code doesn't need input, just let it run normally
        if not code_needs_input:
            print(f"🔧 Process {process_id}: Running without input handling")
            try:
                # Wait for process to complete with timeout
                stdout, stderr = process.communicate(timeout=30)
                
                if stdout:
                    socketio.emit("code_output", {
                        "process_id": process_id,
                        "output": stdout,
                        "type": "stdout"
                    }, room=session_id)
                
                if stderr:
                    socketio.emit("code_output", {
                        "process_id": process_id,
                        "output": stderr,
                        "type": "stderr"
                    }, room=session_id)
                
                # Send completion signal
                socketio.emit("code_complete", {
                    "process_id": process_id,
                    "status": "completed"
                }, room=session_id)
                
                return
                
            except subprocess.TimeoutExpired:
                process.kill()
                socketio.emit("code_output", {
                    "process_id": process_id,
                    "output": "\n⏰ Error: Code execution timed out (30 seconds)\n",
                    "type": "error"
                }, room=session_id)
                return
            except Exception as e:
                socketio.emit("code_output", {
                    "process_id": process_id,
                    "output": f"\n❌ Error: {str(e)}\n",
                    "type": "error"
                }, room=session_id)
                return
        
        # If code needs input, use the input handling logic
        print(f"🔧 Process {process_id}: Running WITH input handling")
        
        # Function to read output from the process
        def read_output():
            while process.poll() is None:
                try:
                    # Use select to check if there's output available
                    ready, _, _ = select.select([process.stdout, process.stderr], [], [], 0.1)
                    
                    for stream in ready:
                        if stream == process.stdout:
                            line = process.stdout.readline()
                            if line:
                                socketio.emit("code_output", {
                                    "process_id": process_id,
                                    "output": line,
                                    "type": "stdout"
                                }, room=session_id)
                        elif stream == process.stderr:
                            line = process.stderr.readline()
                            if line:
                                socketio.emit("code_output", {
                                    "process_id": process_id,
                                    "output": line,
                                    "type": "stderr"
                                }, room=session_id)
                except (IOError, OSError):
                    break
        
        # Start output reading thread
        output_thread = threading.Thread(target=read_output)
        output_thread.daemon = True
        output_thread.start()
        
        # Main loop to handle process execution and input
        start_time = time.time()
        timeout = 30  # 30 seconds timeout
        
        while process.poll() is None:
            if time.time() - start_time > timeout:
                process.kill()
                socketio.emit("code_output", {
                    "process_id": process_id,
                    "output": "\n⏰ Error: Code execution timed out (30 seconds)\n",
                    "type": "error"
                }, room=session_id)
                break
            
            # Check if process needs input (is waiting)
            try:
                # Try to get input from queue with timeout
                user_input = input_queues[process_id].get(timeout=0.1)
                process.stdin.write(user_input)
                process.stdin.flush()
                
                # Notify that input was received
                socketio.emit("input_received", {
                    "process_id": process_id
                }, room=session_id)
                
            except queue.Empty:
                # No input available, continue monitoring
                pass
            except BrokenPipeError:
                # Process has ended
                break
            
            time.sleep(0.05)
        
        # Get any remaining output after process ends
        try:
            remaining_stdout, remaining_stderr = process.communicate(timeout=2)
            if remaining_stdout:
                socketio.emit("code_output", {
                    "process_id": process_id,
                    "output": remaining_stdout,
                    "type": "stdout"
                }, room=session_id)
            if remaining_stderr:
                socketio.emit("code_output", {
                    "process_id": process_id,
                    "output": remaining_stderr,
                    "type": "stderr"
                }, room=session_id)
        except subprocess.TimeoutExpired:
            process.kill()
        
        # Send completion signal
        socketio.emit("code_complete", {
            "process_id": process_id,
            "status": "completed"
        }, room=session_id)
        
    except subprocess.TimeoutExpired:
        socketio.emit("code_output", {
            "process_id": process_id,
            "output": "\n⏰ Error: Code execution timed out (30 seconds)\n",
            "type": "error"
        }, room=session_id)
    except Exception as e:
        socketio.emit("code_output", {
            "process_id": process_id,
            "output": f"\n❌ Error: {str(e)}\n",
            "type": "error"
        }, room=session_id)
    finally:
        # Cleanup
        if process_id in running_processes:
            del running_processes[process_id]
        if process_id in input_queues:
            del input_queues[process_id]
        if process_id in process_needs_input:
            del process_needs_input[process_id]
        # Clean up temporary file
        try:
            if temp_filename and os.path.exists(temp_filename):
                os.unlink(temp_filename)
        except:
            pass

# Add a new endpoint to provide input to running process
@app.route("/provide_input", methods=["POST"])
def provide_input():
    data = request.get_json()
    process_id = data.get("process_id")
    user_input = data.get("user_input", "")
    
    if not process_id or not user_input:
        return jsonify({"status": "error", "message": "Process ID and input are required"})
    
    if process_id in input_queues:
        input_queues[process_id].put(user_input + "\n")
        return jsonify({"status": "success", "message": "Input sent to process"})
    else:
        return jsonify({"status": "error", "message": "Process not found or completed"})

@socketio.on("connect")
def handle_connect():
    print(f"Client connected: {request.sid}")

@socketio.on("disconnect")
def handle_disconnect():
    print(f"Client disconnected: {request.sid}")
    handle_user_leave()

@socketio.on("join_session")
def handle_join(data):
    session_id = data.get("session_id")
    name = data.get("name", "Anonymous")
    sid = request.sid
    
    if session_id not in sessions:
        emit("error", {"msg": "Session not found"})
        return
    
    join_room(session_id)
    session = sessions[session_id]
    
    # Set as host and writer if first user
    if not session["participants"]:
        session["host_id"] = sid
        session["writer_id"] = sid
        print(f"👑 {name} is now host of session {session_id}")
    
    session["participants"][sid] = {
        "name": name,
        "sid": sid
    }
    
    # Send current code to new user
    emit("code_update", {"content": session["content"]})
    
    # Send chat history to new user
    if session["chat_messages"]:
        emit("chat_history", {"messages": session["chat_messages"][-50:]})
    
    # Notify all users about updated participants
    emit_participants_update(session_id)
    
    print(f"👤 {name} joined session {session_id}")

def handle_user_leave():
    """Handle when a user leaves the session"""
    sid = request.sid
    for session_id, session in sessions.items():
        if sid in session["participants"]:
            user_name = session["participants"][sid]["name"]
            
            # Remove user from participants
            del session["participants"][sid]
            
            # Handle host transfer if host left
            if session["host_id"] == sid:
                if session["participants"]:
                    # Transfer host to first available participant
                    new_host_sid = next(iter(session["participants"].keys()))
                    session["host_id"] = new_host_sid
                    session["writer_id"] = new_host_sid
                    new_host_name = session["participants"][new_host_sid]["name"]
                    print(f"👑 Host transferred to {new_host_name} in session {session_id}")
                else:
                    # No participants left, clear host
                    session["host_id"] = None
                    session["writer_id"] = None
            
            # Update all clients
            emit_participants_update(session_id)
            
            print(f"👤 {user_name} left session {session_id}")
            break

def emit_participants_update(session_id):
    """Send updated participants list to all clients in the session"""
    if session_id in sessions:
        session = sessions[session_id]
        emit("participants_update", {
            "participants": session["participants"],
            "writer_id": session["writer_id"],
            "host_id": session["host_id"]
        }, room=session_id)

@socketio.on("get_participants")
def handle_get_participants(data):
    """Get all participants in session"""
    session_id = data.get("session_id")
    sid = request.sid
    
    if session_id in sessions:
        session = sessions[session_id]
        emit("participants_update", {
            "participants": session["participants"],
            "writer_id": session["writer_id"],
            "host_id": session["host_id"]
        })

@socketio.on("code_change")
def handle_code_change(data):
    session_id = data.get("session_id")
    content = data.get("content", "")
    sid = request.sid
    
    if session_id in sessions:
        session = sessions[session_id]
        if session["writer_id"] == sid:
            session["content"] = content
            emit("code_update", {"content": content}, room=session_id, include_self=False)
            print(f"📝 Code updated by {session['participants'][sid]['name']} in session {session_id}")

@socketio.on("grant_write")
def handle_grant_write(data):
    """Grant write access to another user"""
    session_id = data.get("session_id")
    target_sid = data.get("target_sid")
    sid = request.sid
    
    if session_id in sessions:
        session = sessions[session_id]
        if session["host_id"] == sid and target_sid in session["participants"]:
            session["writer_id"] = target_sid
            emit_participants_update(session_id)
            print(f"✏️ Write access granted to {session['participants'][target_sid]['name']}")

@socketio.on("revoke_write")
def handle_revoke_write(data):
    """Revoke write access (host becomes writer)"""
    session_id = data.get("session_id")
    sid = request.sid
    
    if session_id in sessions:
        session = sessions[session_id]
        if session["host_id"] == sid:
            session["writer_id"] = sid
            emit_participants_update(session_id)
            print(f"✏️ Write access revoked by {session['participants'][sid]['name']}")

# WebRTC signaling handlers
@socketio.on("webrtc_offer")
def handle_webrtc_offer(data):
    target_sid = data.get("target")
    offer = data.get("sdp")
    if target_sid:
        emit("webrtc_offer", {
            "sdp": offer,
            "sid": request.sid
        }, to=target_sid)

@socketio.on("webrtc_answer")
def handle_webrtc_answer(data):
    target_sid = data.get("target")
    answer = data.get("sdp")
    if target_sid:
        emit("webrtc_answer", {
            "sdp": answer,
            "sid": request.sid
        }, to=target_sid)

@socketio.on("webrtc_ice_candidate")
def handle_webrtc_ice_candidate(data):
    target_sid = data.get("target")
    candidate = data.get("candidate")
    if target_sid:
        emit("webrtc_ice_candidate", {
            "candidate": candidate,
            "sid": request.sid
        }, to=target_sid)

# Chat functionality
@socketio.on("send_chat_message")
def handle_chat_message(data):
    """Handle chat messages from clients"""
    session_id = data.get("session_id")
    message_text = data.get("message", "").strip()
    sid = request.sid
    
    if not session_id or session_id not in sessions:
        return
    
    if not message_text:
        return
    
    session = sessions[session_id]
    if sid not in session["participants"]:
        return
    
    sender_info = session["participants"][sid]
    sender_name = sender_info["name"]
    
    chat_message = {
        "id": str(uuid.uuid4())[:8],
        "sender_sid": sid,
        "sender_name": sender_name,
        "message": message_text,
        "timestamp": time.time(),
        "time_display": datetime.now().strftime("%H:%M")
    }
    
    session["chat_messages"].append(chat_message)
    
    if len(session["chat_messages"]) > 100:
        session["chat_messages"] = session["chat_messages"][-100:]
    
    emit("new_chat_message", chat_message, room=session_id)
    
    print(f"💬 {sender_name} sent message in session {session_id}: {message_text[:50]}...")

@socketio.on("get_chat_history")
def handle_get_chat_history(data):
    """Send chat history to joining user"""
    session_id = data.get("session_id")
    sid = request.sid
    
    if session_id in sessions and sessions[session_id]["chat_messages"]:
        session = sessions[session_id]
        chat_history = session["chat_messages"][-50:]
        emit("chat_history", {"messages": chat_history})

if __name__ == "__main__":
    print("🚀 Starting SIREN Collaborative Editor...")
    print("📍 Local URL: http://localhost:5000")
    print("💡 Features: Real-time coding, Smart input detection, User management, Chat")
    print("🔧 Running with threading async_mode for better compatibility")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)