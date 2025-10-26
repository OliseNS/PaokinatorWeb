import os
import requests
import json
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, jsonify

# Load environment variables (like GAME_SERVER_URL and a SECRET_KEY)
load_dotenv()

app = Flask(__name__, template_folder='templates')

# A SECRET_KEY is required for Flask sessions
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'a_very_strong_fallback_secret_key_123')

# Get the game server URL from environment variable
GAME_SERVER_URL = os.getenv('GAME_SERVER_URL')

if not GAME_SERVER_URL:
    app.logger.critical("GAME_SERVER_URL environment variable is not set. The application will not be able to contact the game server.")

# --- Helper Function ---

def get_game_server_data(endpoint):
    """Helper to make GET requests to the game server."""
    if not GAME_SERVER_URL:
        return {"error": "Game server is not configured."}
    try:
        response = requests.get(f"{GAME_SERVER_URL}{endpoint}")
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        app.logger.exception(f"Failed to fetch data from upstream server: {endpoint}")
        return {"error": "Upstream game server request failed", "details": str(e)}

def post_game_server_data(endpoint, data):
    """Helper to make POST requests to the game server."""
    if not GAME_SERVER_URL:
        return {"error": "Game server is not configured."}
    try:
        response = requests.post(f"{GAME_SERVER_URL}{endpoint}", json=data)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        app.logger.exception(f"Failed to post data to upstream server: {endpoint}")
        return {"error": "Upstream game server request failed", "details": str(e)}

# --- Page Routes ---

@app.route('/')
def index():
    """Serves the main Home Page (category selection)."""
    # Clear any old session data
    session.clear()
    return render_template('index.html')

@app.route('/start', methods=['POST'])
def start_game():
    """
    Starts a new game session on the game server, stores the
    session_id in the Flask session, and redirects to the play page.
    """
    if not GAME_SERVER_URL:
        return render_template('error.html', message="Game server is not configured.")
        
    data = post_game_server_data('/start', {})
    
    if data and data.get('session_id'):
        session['game_session_id'] = data['session_id']
        return redirect(url_for('play_game'))
    else:
        return render_template('error.html', message="Could not start a new game session.")

@app.route('/play')
def play_game():
    """
    Main game loop page. Renders questions and guesses.
    This single route handles the entire game flow.
    """
    game_session_id = session.get('game_session_id')
    if not game_session_id:
        return redirect(url_for('index'))

    # Get the next question or guess from the game server
    data = get_game_server_data(f"/question/{game_session_id}")

    if data.get('error'):
        # Session might have expired on the server
        return render_template('error.html', message=f"Your session has expired or an error occurred. ({data.get('details')})")
    
    # Store predictions in session for the /isitthis page
    if data.get('top_predictions'):
        session['top_predictions'] = json.dumps(data['top_predictions'])
        
    if data.get('guess'):
        session['last_guess'] = data['guess']

    return render_template('play.html', data=data)

@app.route('/answer', methods=['POST'])
def answer():
    """Handles a user's answer to a question."""
    game_session_id = session.get('game_session_id')
    if not game_session_id:
        return redirect(url_for('index'))

    payload = {
        "feature": request.form.get('feature'),
        "answer": request.form.get('answer'),
        # Handle sneaky guess logic if it was part of the state
        "animal_name": request.form.get('animal_name') if request.form.get('animal_name') else None
    }
    
    data = post_game_server_data(f"/answer/{game_session_id}", payload)

    if data.get('status') == 'guess_correct':
        # The AI's sneaky guess was right!
        return redirect(url_for('win', animal=data.get('animal')))
    
    # Otherwise, just loop back to the play page for the next question
    return redirect(url_for('play_game'))

@app.route('/guess_result', methods=['POST'])
def guess_result():
    """Handles the user's "Yes" or "No" to the AI's final guess."""
    response = request.form.get('response')
    
    if response == 'yes':
        animal = request.form.get('guess')
        return redirect(url_for('win', animal=animal))
    else:
        # User said "No", redirect to the "is it this?" list
        return redirect(url_for('is_it_this'))

@app.route('/isitthis')
def is_it_this():
    """
    Shows the list of other top predictions if the main guess was wrong.
    """
    top_predictions_json = session.get('top_predictions', '[]')
    last_guess = session.get('last_guess')
    
    try:
        predictions = json.loads(top_predictions_json)
        # Filter out the guess they already rejected
        filtered_predictions = [p for p in predictions if p.get('animal') and p.get('animal').lower() != last_guess.lower()]
    except json.JSONDecodeError:
        predictions = []
        filtered_predictions = []
    
    return render_template('isitthis.html', predictions=filtered_predictions)

@app.route('/this')
def this():
    """Shows the form for the user to enter the correct animal."""
    return render_template('this.html')

@app.route('/learn', methods=['POST'])
def learn():
    """Submits the new animal to the learning endpoint."""
    game_session_id = session.get('game_session_id')
    if not game_session_id:
        return redirect(url_for('index'))
        
    animal_name = request.form.get('animal_name')
    if not animal_name:
        # This could happen if they came from /isitthis
        # but didn't pick one
        return redirect(url_for('this'))

    post_game_server_data(f"/learn/{game_session_id}", {"animal_name": animal_name})
    
    return redirect(url_for('thank_you', animal=animal_name))

@app.route('/win')
def win():
    """Shows the "I won!" page."""
    animal = request.args.get('animal', 'your animal')
    session.clear() # Game is over, clear session
    return render_template('win.html', animal=animal)

@app.route('/thank_you')
def thank_you():
    """Shows the "Thanks for teaching me" page."""
    animal = request.args.get('animal', 'that')
    session.clear() # Game is over, clear session
    return render_template('thank_you.html', animal=animal)

@app.route('/add_questions/<animal>')
def add_questions(animal):
    """Page to add new questions for a learned animal."""
    return render_template('add_questions.html', animal=animal)

@app.route('/submit_question', methods=['POST'])
def submit_question():
    """Stub route for the 'add questions' feature."""
    animal = request.form.get('animal')
    question = request.form.get('question')
    # In a real app, you'd POST this to a new backend endpoint
    app.logger.info(f"User suggested question for {animal}: {question}")
    return render_template('feature_soon.html', animal=animal)
    
@app.route('/error')
def error():
    """A generic error page."""
    message = request.args.get('message', 'An unknown error occurred.')
    return render_template('error.html', message=message)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)