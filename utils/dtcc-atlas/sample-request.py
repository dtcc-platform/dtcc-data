import requests
import json

# Define the API endpoint
url = 'http://localhost:5000/api/post/boundingbox'

# Define the payload for the POST request
payload = {
    'points': [
        0,
        1000,
        500,
        1500
    ]
}

# Send a POST request
response = requests.post(url, json=payload)

# Check the status code to see if the request was successful
if response.status_code == 200:
    print('Success!')
    print('Response:', response.json())
else:
    print('Failed to get a valid response:', response.status_code)
    print('Response:', response.text)
