#!/bin/sh
set -e

# Bootstrap the repository before Python imports try to access it
if [ -n "$PERSONAL_AI_DATA" ]; then
    echo "Deployed mode: PERSONAL_AI_DATA=$PERSONAL_AI_DATA"

    # Ensure data directory exists
    mkdir -p "$PERSONAL_AI_DATA/state"

    # Set up SSH key if provided
    if [ -n "$GIT_SSH_KEY" ]; then
        echo "Installing deploy key..."
        echo "$GIT_SSH_KEY" > "$PERSONAL_AI_DATA/deploy_key"
        chmod 600 "$PERSONAL_AI_DATA/deploy_key"
        export GIT_SSH_COMMAND="ssh -i $PERSONAL_AI_DATA/deploy_key -o StrictHostKeyChecking=accept-new"
    fi

    # Clone repo if it doesn't exist
    if [ ! -d "$PERSONAL_AI_DATA/repo/.git" ]; then
        if [ -n "$GIT_REMOTE_URL" ]; then
            echo "First boot: cloning $GIT_REMOTE_URL to $PERSONAL_AI_DATA/repo"
            git clone "$GIT_REMOTE_URL" "$PERSONAL_AI_DATA/repo"
        else
            echo "ERROR: No repo at $PERSONAL_AI_DATA/repo and GIT_REMOTE_URL not set"
            exit 1
        fi
    else
        echo "Repository exists, pulling latest..."
        cd "$PERSONAL_AI_DATA/repo"
        git pull --ff-only || echo "Warning: git pull failed, continuing with local copy"
        cd /app
    fi
fi

# Start the application
echo "Starting application..."
exec uv run python -m agent.main
