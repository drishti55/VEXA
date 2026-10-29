import os
import requests
import dotenv

dotenv.load_dotenv('.env')
key = os.environ.get('VEXA_LLM_API_KEY')
res = requests.get('https://api.groq.com/openai/v1/models', headers={'Authorization': f'Bearer {key}'})
data = res.json()
print([m['id'] for m in data.get('data', [])])
