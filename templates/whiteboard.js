const socket = io();
const canvas = document.getElementById('whiteboard');
const ctx = canvas.getContext('2d');

// DOM Elements
const statusEl = document.getElementById('status');
const userCountEl = document.getElementById('userCount');
const sessionIdInput = document.getElementById('sessionIdInput');
const userNameInput = document.getElementById('userNameInput');
const createBtn = document.getElementById('createBtn');
const joinBtn = document.getElementById('joinBtn');
const leaveBtn = document.getElementById('leaveBtn');
const sessionInfo = document.getElementById('sessionInfo');
const currentSessionEl = document.getElementById('currentSession');
const currentUserEl = document.getElementById('currentUser');
const whiteboardControls = document.getElementById('whiteboardControls');
const usersList = document.getElementById('usersList');
const usersContainer = document.getElementById('usersContainer');
const clearBtn = document.getElementById('clearBtn');
const brushSize = document.getElementById('brushSize');
const brushSizeValue = document.getElementById('brushSizeValue');

// Whiteboard state
let isDrawing = false;
let lastX = 0;
let lastY = 0;
let currentColor = 'black';
let currentBrushSize = 3;

// Session state
let currentSession = null;
let currentUser = null;
let users = new Map(); // user_id -> user_data

// Initialize canvas
ctx.fillStyle = 'white';
ctx.fillRect(0, 0, canvas.width, canvas.height);

// Socket event handlers
socket.on('connect', () => {
    statusEl.textContent = 'Connected';
    statusEl.style.color = '#4CAF50';
    updateUI();
});

socket.on('disconnect', () => {
    statusEl.textContent = 'Disconnected';
    statusEl.style.color = '#f44336';
    leaveSession();
});

// Session events
socket.on('session_created', (data) => {
    console.log('Session created:', data);
    joinSession(data.session_id, data.user_name);
});

socket.on('session_joined', (data) => {
    console.log('Session joined:', data);
    joinSession(data.session_id, data.user_name);
});

socket.on('session_error', (data) => {
    alert('Error: ' + data.message);
});

socket.on('user_joined', (data) => {
    users.set(data.user_id, data);
    updateUsersList();
    updateUserCount();
});

socket.on('user_left', (data) => {
    users.delete(data.user_id);
    updateUsersList();
    updateUserCount();
});

socket.on('users_list', (data) => {
    users = new Map(data.users.map(user => [user.user_id, user]));
    updateUsersList();
    updateUserCount();
});

// Whiteboard events
socket.on('drawing', (data) => {
    if (data.session_id === currentSession) {
        drawOnCanvas(data.x0, data.y0, data.x1, data.y1, data.color, data.size);
    }
});

socket.on('clear', (data) => {
    if (data.session_id === currentSession) {
        clearCanvas();
    }
});

socket.on('whiteboard_state', (data) => {
    if (data.session_id === currentSession) {
        // For a real implementation, you might want to store and replay the drawing history
        clearCanvas();
    }
});

// Drawing functions
function drawOnCanvas(x0, y0, x1, y1, color, size) {
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y1);
    ctx.strokeStyle = color;
    ctx.lineWidth = size;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.stroke();
    ctx.closePath();
}

function clearCanvas() {
    ctx.fillStyle = 'white';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
}

function startDrawing(e) {
    if (!currentSession) return;
    isDrawing = true;
    [lastX, lastY] = getCoordinates(e);
}

function draw(e) {
    if (!isDrawing || !currentSession) return;
    
    const [x, y] = getCoordinates(e);
    
    // Draw locally
    drawOnCanvas(lastX, lastY, x, y, currentColor, currentBrushSize);
    
    // Send drawing data to server
    socket.emit('drawing', {
        session_id: currentSession,
        x0: lastX,
        y0: lastY,
        x1: x,
        y1: y,
        color: currentColor,
        size: currentBrushSize
    });
    
    [lastX, lastY] = [x, y];
}

function stopDrawing() {
    isDrawing = false;
}

function getCoordinates(e) {
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    
    let clientX, clientY;
    
    if (e.type.includes('touch')) {
        clientX = e.touches[0].clientX;
        clientY = e.touches[0].clientY;
    } else {
        clientX = e.clientX;
        clientY = e.clientY;
    }
    
    return [
        (clientX - rect.left) * scaleX,
        (clientY - rect.top) * scaleY
    ];
}

// Session management
function createSession() {
    const sessionId = sessionIdInput.value.trim() || generateSessionId();
    const userName = userNameInput.value.trim() || 'Anonymous';
    
    if (!userName) {
        alert('Please enter your name');
        return;
    }
    
    socket.emit('create_session', {
        session_id: sessionId,
        user_name: userName
    });
}

function joinSession(sessionId, userName) {
    currentSession = sessionId;
    currentUser = userName;
    
    // Update UI
    currentSessionEl.textContent = sessionId;
    currentUserEl.textContent = userName;
    sessionInfo.style.display = 'block';
    whiteboardControls.style.display = 'flex';
    canvas.style.display = 'block';
    usersList.style.display = 'block';
    
    createBtn.style.display = 'none';
    joinBtn.style.display = 'none';
    leaveBtn.style.display = 'inline-block';
    sessionIdInput.disabled = true;
    userNameInput.disabled = true;
    
    // Request current whiteboard state
    socket.emit('get_whiteboard_state', { session_id: sessionId });
}

function leaveSession() {
    if (currentSession) {
        socket.emit('leave_session', { session_id: currentSession });
    }
    
    currentSession = null;
    currentUser = null;
    users.clear();
    
    // Reset UI
    sessionInfo.style.display = 'none';
    whiteboardControls.style.display = 'none';
    canvas.style.display = 'none';
    usersList.style.display = 'none';
    
    createBtn.style.display = 'inline-block';
    joinBtn.style.display = 'inline-block';
    leaveBtn.style.display = 'none';
    sessionIdInput.disabled = false;
    userNameInput.disabled = false;
    
    updateUsersList();
    updateUserCount();
}

function generateSessionId() {
    return Math.random().toString(36).substring(2, 8).toUpperCase();
}

function updateUI() {
    updateUserCount();
    updateUsersList();
}

function updateUserCount() {
    userCountEl.textContent = `Users: ${users.size}`;
}

function updateUsersList() {
    usersContainer.innerHTML = '';
    users.forEach((userData, userId) => {
        const userEl = document.createElement('div');
        userEl.className = 'user-item';
        userEl.textContent = userData.user_name + (userId === socket.id ? ' (You)' : '');
        usersContainer.appendChild(userEl);
    });
}

// Event listeners for session controls
createBtn.addEventListener('click', createSession);

joinBtn.addEventListener('click', () => {
    const sessionId = sessionIdInput.value.trim();
    const userName = userNameInput.value.trim() || 'Anonymous';
    
    if (!sessionId) {
        alert('Please enter a session ID');
        return;
    }
    
    if (!userName) {
        alert('Please enter your name');
        return;
    }
    
    socket.emit('join_session', {
        session_id: sessionId,
        user_name: userName
    });
});

leaveBtn.addEventListener('click', leaveSession);

// Event listeners for whiteboard
canvas.addEventListener('mousedown', startDrawing);
canvas.addEventListener('mousemove', draw);
canvas.addEventListener('mouseup', stopDrawing);
canvas.addEventListener('mouseout', stopDrawing);

// Touch support
canvas.addEventListener('touchstart', (e) => {
    e.preventDefault();
    startDrawing(e);
});
canvas.addEventListener('touchmove', (e) => {
    e.preventDefault();
    draw(e);
});
canvas.addEventListener('touchend', (e) => {
    e.preventDefault();
    stopDrawing();
});

// Whiteboard controls
clearBtn.addEventListener('click', () => {
    if (!currentSession) return;
    clearCanvas();
    socket.emit('clear', { session_id: currentSession });
});

// Color picker
document.querySelectorAll('.color-option').forEach(option => {
    option.addEventListener('click', () => {
        document.querySelectorAll('.color-option').forEach(opt => {
            opt.classList.remove('active');
        });
        option.classList.add('active');
        currentColor = option.dataset.color;
    });
});

// Brush size
brushSize.addEventListener('input', (e) => {
    currentBrushSize = parseInt(e.target.value);
    brushSizeValue.textContent = currentBrushSize;
});

// Auto-generate session ID if empty
sessionIdInput.addEventListener('focus', () => {
    if (!sessionIdInput.value) {
        sessionIdInput.value = generateSessionId();
    }
});

console.log('🎨 Whiteboard with Session Management ready!');