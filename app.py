
import os
from dotenv import load_dotenv
import requests
from flask import Flask, render_template, jsonify, request

load_dotenv()
# Get the game server URL from environment variable with a fallback
GAME_SERVER_URL = os.getenv('GAME_SERVER_URL')
app = Flask(__name__, template_folder='templates', static_folder='static')

@app.route('/')
def index():
    """Serves the main HTML game page."""
    return render_template('index.html')


@app.route('/api/start', methods=['POST'])
def start_game():
    """Starts a new game session on the game server."""
    try:
        response = requests.post(f"{GAME_SERVER_URL}/start")
        response.raise_for_status()
        return jsonify(response.json())
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/question/<session_id>', methods=['GET'])
def get_question(session_id):
    """Gets the next question from the game server and logs predictions."""
    try:
        response = requests.get(f"{GAME_SERVER_URL}/question/{session_id}")
        response.raise_for_status()
        data = response.json()
        

        
        return jsonify(data)
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/answer/<session_id>', methods=['POST'])
def submit_answer(session_id):
    """Submits an answer to the game server and logs predictions."""
    try:
        data = request.get_json()
        response = requests.post(f"{GAME_SERVER_URL}/answer/{session_id}", json=data)
        response.raise_for_status()
        response_data = response.json()

        return jsonify(response_data)
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/reject/<session_id>', methods=['POST'])
def reject_guess(session_id):
    """Rejects a guess on the game server."""
    try:
        data = request.get_json()
        response = requests.post(f"{GAME_SERVER_URL}/reject/{session_id}", json=data)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/learn/<session_id>', methods=['POST'])
def learn_animal(session_id):
    """Sends the correct animal name to the game server for learning."""
    try:
        data = request.get_json()
        response = requests.post(f"{GAME_SERVER_URL}/learn/{session_id}", json=data)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5001))
    app.run(host='0.0.0.0', port=port)