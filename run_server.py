#!/usr/bin/env python3
import os
import sys

# Set up environment
os.chdir('/root/VoiceClaude')

# Import and run the app
from app import app

if __name__ == '__main__':
    print('=' * 50)
    print('CLAUDE VOICE ASSISTANT - SERVER MODE')
    print('=' * 50)
    print(f'Access URL: http://104.238.129.211:5000')
    print('=' * 50)
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
