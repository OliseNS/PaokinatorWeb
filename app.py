import os
import requests
import json
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
# Supabase imports are removed, as they are now in mod_routes.py

# NEW: Import the Blueprint from our new file
from mod_routes import mod_bp

load_dotenv()

app = Flask(__name__, template_folder='templates')

# A SECRET_KEY is required for Flask sessions
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'a_very_strong_fallback_secret_key_123')

# Get the game server URL from environment variable
GAME_SERVER_URL = os.getenv('GAME_SERVER_URL')

if not GAME_SERVER_URL:
    app.logger.critical("GAME_SERVER_URL environment variable is not set. The application will not be able to contact the game server.")

# --- Supabase Client Setup has been REMOVED from this file ---
# --- It now lives in mod_routes.py ---


# NEW: Fuzzy map to convert user answers to numbers for feature suggestions
FUZZY_MAP = {
    'yes': 1.0,
    'probably': 0.75,
    'sometimes': 0.5,
    'rarely': 0.25,
    'no': 0.0
}

# --- Helper Function ---

def get_game_server_data(endpoint):
    """Helper to make GET requests to the game server."""
    if not GAME_SERVER_URL:
        return {"error": "Game server is not configured."}
    try:
        url = f"{GAME_SERVER_URL.rstrip('/')}{endpoint}"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        app.logger.exception(f"Failed to fetch data from upstream server: {url}")
        return {"error": "Upstream game server request failed", "details": str(e)}

def post_game_server_data(endpoint, data):
    """Helper to make POST requests to the game server."""
    if not GAME_SERVER_URL:
        return {"error": "Game server is not configured."}
    try:
        url = f"{GAME_SERVER_URL.rstrip('/')}{endpoint}"
        response = requests.post(url, json=data)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        app.logger.exception(f"Failed to post data to upstream server: {url}")
        return {"error": "Upstream game server request failed", "details": str(e)}

# --- Page Routes ---

@app.route('/')
def index():
    """Serves the main Home Page (domain selection)."""
    # Clear any old session data
    session.clear()
    
    # NEW: Fetch available domains from the backend
    data = get_game_server_data('/domains')
    if data.get('error'):
        app.logger.error(f"Could not fetch domains: {data.get('details')}")
        return render_template('error.html', message="Could not fetch game domains from server.")
        
    domains = data.get('domains', ['animals']) # Default to 'animals' if fetch fails
    
    return render_template('index.html', domains=domains)

@app.route('/start', methods=['POST'])
def start_game():
    """
    Starts a new game session on the game server, stores the
    session_id and domain_name in the Flask session, and redirects to the play page.
    """
    if not GAME_SERVER_URL:
        return render_template('error.html', message="Game server is not configured.")
        
    # MODIFIED: Send the selected domain_name to the /start endpoint
    domain_name = request.form.get('domain_name', 'animals')
    payload = {"domain_name": domain_name}
    data = post_game_server_data('/start', payload)
    
    if data and data.get('session_id'):
        session['game_session_id'] = data['session_id']
        session['domain_name'] = data['domain_name'] # NEW: Store domain in session
        return redirect(url_for('play_game'))
    else:
        app.logger.error(f"Could not start game. Response: {data}")
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
    """
    DEPRECATED: This was the old form-based route.
    Kept for reference, but /api/answer is used by play.html now.
    """
    return redirect(url_for('play_game'))


# --- API ROUTES (for JavaScript) ---
@app.route('/api/answer', methods=['POST'])
def api_answer():
    """
    Handles a user's answer via JSON and returns the next game state as JSON,
    preventing a full page reload.
    """
    game_session_id = session.get('game_session_id')
    if not game_session_id:
        return jsonify({"error": "No game session"}), 400

    req_data = request.json
    payload = {
        "feature": req_data.get('feature'),
        "answer": req_data.get('answer'),
        "animal_name": req_data.get('animal_name')
    }

    # 1. Post the answer to the game server
    answer_response = post_game_server_data(f"/answer/{game_session_id}", payload)

    if answer_response.get('status') == 'guess_correct':
        # 2. If the sneaky guess was right, tell the client to redirect
        return jsonify({"redirect_url": url_for('confirm_win_route', animal=answer_response.get('animal'))})
    
    if answer_response.get('error'):
        return jsonify({"error": answer_response.get('details', 'Failed to post answer')}), 500

    # 3. If not, get the next question/game state
    next_game_state = get_game_server_data(f"/question/{game_session_id}")

    if next_game_state.get('error'):
        return jsonify({"redirect_url": url_for('error', message=f"Your session has expired or an error occurred. ({next_game_state.get('details')})")})

    if next_game_state.get('top_predictions'):
        session['top_predictions'] = json.dumps(next_game_state['top_predictions'])
        
    if next_game_state.get('guess'):
        session['last_guess'] = next_game_state['guess']
    
    return jsonify(next_game_state)


# --- NEW API ROUTE ---
@app.route('/api/reject_guess', methods=['POST'])
def api_reject_guess():
    """
    Handles the user clicking "No, that's wrong" on a final guess.
    Calls the backend /reject endpoint and returns its JSON response.
    """
    game_session_id = session.get('game_session_id')
    if not game_session_id:
        return jsonify({"error": "No game session"}), 400
    
    req_data = request.json
    animal_name = req_data.get('guess')
    if not animal_name:
        return jsonify({"error": "No animal name provided"}), 400
    
    # Call the backend /reject endpoint
    reject_response = post_game_server_data(f"/reject/{game_session_id}", {"animal_name": animal_name})

    if reject_response.get('error'):
        return jsonify({"error": reject_response.get('details', 'Failed to reject guess')}), 500

    # This should return {'status': 'ask_to_continue', ...}
    return jsonify(reject_response)


# --- NEW API ROUTE ---
@app.route('/api/continue_game', methods=['POST'])
def api_continue_game():
    """
    Handles the user clicking "Yes" to continue.
    Calls the backend /continue endpoint and then fetches the next question.
    """
    game_session_id = session.get('game_session_id')
    if not game_session_id:
        return jsonify({"error": "No game session"}), 400

    # 1. Tell the backend to continue
    continue_response = post_game_server_data(f"/continue/{game_session_id}", {})
    
    if continue_response.get('status') != 'continuing':
        return jsonify({"error": continue_response.get('details', 'Failed to set continue mode')}), 500

    # 2. Get the next question
    next_game_state = get_game_server_data(f"/question/{game_session_id}")
    
    if next_game_state.get('error'):
        return jsonify({"redirect_url": url_for('error', message=f"Your session has expired or an error occurred. ({next_game_state.get('details')})")})
    
    # Store predictions in case this next state is a guess
    if next_game_state.get('top_predictions'):
        session['top_predictions'] = json.dumps(next_game_state['top_predictions'])
    if next_game_state.get('guess'):
        session['last_guess'] = next_game_state['guess']
    
    return jsonify(next_game_state)


# --- NEW API ROUTE ---
@app.route('/api/undo', methods=['POST'])
def api_undo():
    """
    Handles the user clicking "Undo" to go back to the previous question.
    Calls the backend /undo endpoint and returns the reverted game state.
    """
    game_session_id = session.get('game_session_id')
    if not game_session_id:
        return jsonify({"error": "No game session"}), 400

    # 1. Tell the backend to undo
    undo_response = post_game_server_data(f"/undo/{game_session_id}", {})
    
    if undo_response.get('error'):
        return jsonify({"error": undo_response.get('details', 'Failed to undo')}), 500

    # 2. The response *is* the reverted game state.
    # We need to store predictions/guess in session, just like other routes do.
    if undo_response.get('top_predictions'):
        session['top_predictions'] = json.dumps(undo_response['top_predictions'])
    if undo_response.get('guess'):
        session['last_guess'] = undo_response['guess']
    
    return jsonify(undo_response)


@app.route('/guess_result', methods=['POST'])
def guess_result():
    """
    Handles the user's "Yes" to the AI's final guess.
    The "No" is now handled by /api/reject_guess.
    """
    response = request.form.get('response')
    animal = request.form.get('guess')
    
    if response == 'yes':
        # MODIFIED: Redirect to /confirm_win to properly log the win
        return redirect(url_for('confirm_win_route', animal=animal))
    else:
        # This branch should no longer be hit if JS is enabled,
        # but we'll keep it as a fallback.
        game_session_id = session.get('game_session_id')
        if game_session_id:
            # This will return 'ask_to_continue' but the form can't handle it.
            # It will just redirect to is_it_this, which is acceptable fallback.
            post_game_server_data(f"/reject/{game_session_id}", {"animal_name": animal})
        
        # Redirect to the "is it this?" list
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
        filtered_predictions = [p for p in predictions if p.get('animal') and p.get('animal').lower() != (last_guess or '').lower()]
    except json.JSONDecodeError:
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
        return redirect(url_for('this'))

    # The backend /learn endpoint automatically gets domain from session
    post_game_server_data(f"/learn/{game_session_id}", {"animal_name": animal_name})
    
    # MODIFIED: Pass domain to thank_you page
    domain_name = session.get('domain_name', 'animals')
    return redirect(url_for('thank_you', animal=animal_name, domain=domain_name))

# NEW: Route to handle confirming a win from the /isitthis list
@app.route('/confirm_win/<animal_name>')
def confirm_win_from_list(animal_name):
    """
    Confirms a win when the user selects an animal
    from the 'is it this' list.
    """
    return redirect(url_for('confirm_win_route', animal=animal_name))

# MODIFIED: Renamed /win to /confirm_win_route to avoid conflict with template name
@app.route('/confirm_win')
def confirm_win_route():
    """
    Logs the win on the backend, then shows the "I won!" page.
    This is now the single point of entry for a confirmed win.
    """
    animal = request.args.get('animal', 'your animal')
    game_session_id = session.get('game_session_id')
    domain_name = session.get('domain_name', 'animals')

    if game_session_id:
        # MODIFIED: Call POST /win/{session_id} to log the suggestion
        post_game_server_data(f"/win/{game_session_id}", {"animal_name": animal})
        session.pop('game_session_id', None) # Clear only game_id, keep domain
    
    return render_template('win.html', animal=animal, domain=domain_name)

@app.route('/thank_you')
def thank_you():
    """Shows the "Thanks for teaching me" page."""
    animal = request.args.get('animal', 'that')
    domain_name = request.args.get('domain', 'animals')
    session.pop('game_session_id', None) # Clear only game_id, keep domain
    return render_template('thank_you.html', animal=animal, domain=domain_name)

@app.route('/add_questions/<animal>')
def add_questions(animal):
    """Page to add new questions for a learned animal."""
    domain_name = session.get('domain_name', 'animals') # Get domain from session
    if not domain_name:
        flash("Your session has expired, please start over.", "error")
        return redirect(url_for('index'))
        
    # NEW: Fetch other items from this domain to ask questions about
    # This assumes an endpoint /items_for_questions/<domain> exists on the game server
    other_items_data = get_game_server_data(f"/items_for_questions/{domain_name}")
    
    other_animals = []
    if other_items_data and not other_items_data.get('error'):
        # Filter out the current animal from the list, just in case
        other_animals = [
            item for item in other_items_data.get('items', []) 
            if item.lower() != animal.lower()
        ]
        # You could limit the list size here, e.g., other_animals = other_animals[:5]
        
    return render_template(
        'add_questions.html', 
        animal=animal, 
        domain=domain_name,
        other_animals=other_animals  # Pass the new list to the template
    )

@app.route('/submit_question', methods=['POST'])
def submit_question():
    """
    MODIFIED: This route now submits MULTIPLE feature suggestions
    based on the new form, one for each animal provided.
    """
    try:
        # 1. Read common data from the form
        domain_name = request.form.get('domain_name')
        item_name = request.form.get('animal') # This is the main animal
        feature_name = request.form.get('feature_name')
        question_text = request.form.get('question_text')
        
        if not all([domain_name, item_name, feature_name, question_text]):
            flash("All fields (feature, question, and main answer) are required.", "error")
            return redirect(url_for('add_questions', animal=item_name))

        # 2. Loop through all form data to find answers
        payloads_to_submit = []
        main_answer_provided = False

        for key, answer_value in request.form.items():
            if key.startswith('answer_for_'):
                # Extract the animal name from the key: "answer_for_Lion" -> "Lion"
                current_item_name = key[len('answer_for_'):]
                
                # Skip "I Don't Know"
                if answer_value == 'idk':
                    continue
                    
                # Convert answer to fuzzy value
                fuzzy_value = FUZZY_MAP.get(answer_value)
                if fuzzy_value is None:
                    # This shouldn't happen with the select, but good to check
                    flash(f"Invalid answer '{answer_value}' for {current_item_name}.", "error")
                    continue
                
                # Check if this is the main animal's answer
                if current_item_name.lower() == item_name.lower():
                    main_answer_provided = True

                # Construct payload for the backend
                payload = {
                    "domain_name": domain_name,
                    "feature_name": feature_name,
                    "question_text": question_text,
                    "item_name": current_item_name,
                    "fuzzy_value": fuzzy_value
                }
                payloads_to_submit.append(payload)

        # 3. Validate that the main animal's answer was provided (as required by user)
        if not main_answer_provided:
            flash(f"You must provide a valid answer for {item_name}.", "error")
            return redirect(url_for('add_questions', animal=item_name))
            
        # 4. Post each valid payload to the backend
        errors = []
        success_count = 0
        for payload in payloads_to_submit:
            response = post_game_server_data('/suggest_feature', payload)
            if response.get('status') != 'ok':
                errors.append(f"Could not submit for {payload['item_name']}: {response.get('message', 'Unknown error')}")
            else:
                success_count += 1
        
        if errors:
            # If there were errors, flash them but still proceed
            flash(f"Successfully submitted {success_count} features. Errors: {'; '.join(errors)}", "warning")
        else:
            flash(f"Successfully submitted {success_count} new feature facts!", "success")
        
        # 5. Redirect to thank you page
        return redirect(url_for('thank_you', animal=item_name, domain=domain_name))
            
    except Exception as e:
        app.logger.exception("Failed to submit question")
        return render_template('error.html', message=f"An internal error occurred: {e}")

# --- NEW ROUTE for Data Collection ---
@app.route('/teach_me/<animal>')
def teach_me(animal):
    """
    Shows a page with 5 questions for an existing animal to gather more data.
    """
    domain_name = session.get('domain_name', 'animals')
    if not domain_name:
        flash("Your session has expired, please start over.", "error")
        return redirect(url_for('index'))
    
    # Call the new backend endpoint
    endpoint = f"/features_for_data_collection/{domain_name}?item_name={animal}"
    data = get_game_server_data(endpoint)
    
    if data.get('error'):
        app.logger.error(f"Could not fetch features for data collection: {data.get('details')}")
        flash("Could not load questions for that animal.", "error")
        return redirect(url_for('index'))
    
    features = data.get('features', [])
    
    return render_template(
        'teach_me.html',
        animal=animal,
        domain=domain_name,
        features=features
    )

# --- NEW ROUTE to handle submission from /teach_me ---
@app.route('/submit_teaching', methods=['POST'])
def submit_teaching():
    """
    Submits the 5 answers from the /teach_me page.
    This re-uses the /suggest_feature backend endpoint.
    """
    try:
        domain_name = request.form.get('domain_name')
        animal_name = request.form.get('animal_name')

        if not domain_name or not animal_name:
            flash("Your session or data was invalid. Please try again.", "error")
            return redirect(url_for('index'))

        payloads_to_submit = []
        
        # Loop based on index, assuming up to 5 features
        for i in range(5):
            answer_key = f'answer_{i}'
            feature_key = f'feature_name_{i}'
            question_key = f'question_{i}'
            
            if feature_key not in request.form:
                continue # This loop index didn't exist

            answer_value = request.form.get(answer_key)
            feature_name = request.form.get(feature_key)
            question_text = request.form.get(question_key)

            # Skip "I Don't Know"
            if answer_value == 'idk':
                continue
                
            # Convert answer to fuzzy value
            fuzzy_value = FUZZY_MAP.get(answer_value)
            
            if fuzzy_value is not None:
                payload = {
                    "domain_name": domain_name,
                    "feature_name": feature_name,
                    "question_text": question_text,
                    "item_name": animal_name,
                    "fuzzy_value": fuzzy_value
                }
                payloads_to_submit.append(payload)

        # Post each valid payload to the backend
        errors = []
        success_count = 0
        for payload in payloads_to_submit:
            response = post_game_server_data('/suggest_feature', payload)
            if response.get('status') != 'ok':
                errors.append(f"Could not submit for {payload['feature_name']}: {response.get('message', 'Unknown error')}")
            else:
                success_count += 1
        
        if errors:
            flash(f"Successfully submitted {success_count} answers. Errors: {'; '.join(errors)}", "warning")
        else:
            flash(f"Thank you! Successfully submitted {success_count} new facts!", "success")
        
        # Redirect to thank you page
        return redirect(url_for('thank_you', animal=animal_name, domain=domain_name))

    except Exception as e:
        app.logger.exception("Failed to submit teaching data")
        return render_template('error.html', message=f"An internal error occurred: {e}")


app.register_blueprint(mod_bp)


@app.route('/error')
def error():
    """A generic error page."""
    message = request.args.get('message', 'An unknown error occurred.')
    return render_template('error.html', message=message)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=False)