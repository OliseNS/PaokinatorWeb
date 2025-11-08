import os
import logging
from dotenv import load_dotenv
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from supabase import create_client, Client
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") 

# Initialize the Supabase client
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    logging.critical("MOD_ROUTES: SUPABASE_URL and SUPABASE_KEY environment variables are not set. Moderator panel will not work.")
# --- End Supabase Setup ---

mod_bp = Blueprint('moderator', __name__, template_folder='templates')



@mod_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Renders the login page and handles login logic.
    """
    if request.method == 'POST':
        if not supabase:
            flash("Database client is not configured. Cannot log in.", "error")
            return render_template('login.html')

        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template('login.html')

        try:
            response = supabase.table('moderators').select('*').eq('username', username).single().execute()
            
            if response.data:
                mod = response.data
                
                if mod["password_hash"] == password:
                    session['is_mod'] = True
                    session['mod_username'] = mod['username']
                    flash('Login successful!', 'success')
                    return redirect(url_for('moderator.mod_panel'))
                else:
                    flash('Invalid username or password.', 'error')
                    
            else:
                flash('Invalid username or password.', 'error')

        except Exception as e:
            logging.exception("Login error")
            flash(f"An error occurred during login. Check logs.", "error")
        return render_template('login.html')

    # For GET request
    return render_template('login.html')

@mod_bp.route('/logout')
def logout():
    """Logs the moderator out by clearing the session."""
    session.pop('is_mod', None)
    session.pop('mod_username', None)
    flash('You have been logged out.', 'success')
    return redirect(url_for('moderator.login'))


@mod_bp.route('/mod')
def mod_panel():
    """
    Main moderator panel. Shows suggested features and items.
    """
    
    # --- SECURITY CHECK ---
    if not session.get('is_mod'):
        flash("You must be logged in to access the mod panel.", "error")
        return redirect(url_for('moderator.login'))
    
    
    if not supabase:
        flash("Supabase client is not configured. Mod panel is unavailable.", "error")
        return render_template('mod.html', features=[], items=[])
    
    features = []
    suggested_items = []
    
    try:
        response_features = supabase.table('features').select('*').eq('status', 'suggested').execute()
        
        if response_features.data:
            features = response_features.data
            
    except Exception as e:
        logging.exception("Failed to fetch features from Supabase")
        flash(f"Error fetching features from Supabase: {e}", "error")

    try:
        response_items = supabase.table('items').select('*, domains(domain_name)').eq('status', 'suggested').execute()
        
        if response_items.data:
            suggested_items = response_items.data
            
    except Exception as e:
        logging.exception("Failed to fetch suggested items from Supabase")
        flash(f"Error fetching suggested items from Supabase: {e}", "error")

    return render_template('mod.html', features=features, items=suggested_items)


@mod_bp.route('/mod/approve/<feature_id>')
def mod_approve_feature(feature_id):
    """
    Approves a feature by updating its status to 'active'.
    """
    # --- SECURITY CHECK ---
    if not session.get('is_mod'):
        flash("You must be logged in to perform this action.", "error")
        return redirect(url_for('moderator.login'))
    
    if not supabase:
        flash("Supabase client is not configured.", "error")
        return redirect(url_for('moderator.mod_panel'))
        
    try:
        supabase.table('features').update({'status': 'active'}).eq('id', feature_id).execute()
        flash(f"Feature approved successfully.", "success")
    except Exception as e:
        logging.exception(f"Error approving feature {feature_id}")
        flash(f"Error approving feature: {e}", "error")
    
    return redirect(url_for('moderator.mod_panel')) 

@mod_bp.route('/mod/reject/<feature_id>')
def mod_reject_feature(feature_id):
    """
    Rejects (deletes) a suggested feature from the database.
    """
    if not session.get('is_mod'):
        flash("You must be logged in to perform this action.", "error")
        return redirect(url_for('moderator.login'))
    
    if not supabase:
        flash("Supabase client is not configured.", "error")
        return redirect(url_for('moderator.mod_panel'))
        
    try:
        supabase.table('features').delete().eq('id', feature_id).execute()
        flash(f"Feature rejected and deleted.", "success")
    except Exception as e:
        logging.exception(f"Error rejecting feature {feature_id}")
        flash(f"Error rejecting feature: {e}", "error")
    
    return redirect(url_for('moderator.mod_panel')) 

@mod_bp.route('/mod/approve/item/<item_id>')
def mod_approve_item(item_id):
    """
    Approves a suggested item by updating its status to 'active'.
    """
    if not session.get('is_mod'):
        flash("You must be logged in to perform this action.", "error")
        return redirect(url_for('moderator.login'))
    
    if not supabase:
        flash("Supabase client is not configured.", "error")
        return redirect(url_for('moderator.mod_panel'))
        
    try:
        supabase.table('items').update({'status': 'active'}).eq('id', item_id).execute()
        flash(f"Item approved successfully.", "success")
    except Exception as e:
        logging.exception(f"Error approving item {item_id}")
        flash(f"Error approving item: {e}", "error")
    
    return redirect(url_for('moderator.mod_panel')) 

@mod_bp.route('/mod/reject/item/<item_id>')
def mod_reject_item(item_id):
    """
    Rejects (deletes) a suggested item.
    This also deletes related entries in 'item_features'.
    """
    if not session.get('is_mod'):
        flash("You must be logged in to perform this action.", "error")
        return redirect(url_for('moderator.login'))
    
    if not supabase:
        flash("Supabase client is not configured.", "error")
        return redirect(url_for('moderator.mod_panel'))
        
    try:
        supabase.table('item_features').delete().eq('item_id', item_id).execute()
        
        supabase.table('items').delete().eq('id', item_id).execute()
        
        flash(f"Item rejected and deleted (along with its feature links).", "success")
    except Exception as e:
        logging.exception(f"Error rejecting item {item_id}")
        flash(f"Error rejecting item: {e}", "error")
    
    return redirect(url_for('moderator.mod_panel'))