# Paokinator Web Interface

A web interface for the Paokinator game.

## Local Development

1. Create a `.env` file with the following variables:
   ```
   GAME_SERVER_URL=http://127.0.0.1:5000
   PORT=5001
   ```

2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Run the application:
   ```
   python app.py
   ```

## Railway Deployment

1. Connect your GitHub repository to Railway
2. Set the following environment variables in Railway's dashboard:
   - `GAME_SERVER_URL`: URL of your game server
   - Railway will automatically set the `PORT` variable

3. Railway will automatically:
   - Install dependencies from `requirements.txt`
   - Use the Procfile to run the application
   - Deploy your application

## Environment Variables

- `GAME_SERVER_URL`: URL of the game server (required)
- `PORT`: Port to run the application on (provided by Railway in production)