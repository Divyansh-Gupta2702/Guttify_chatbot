Guttify AI Assistant

Guttify AI Assistant is a conversational product recommendation chatbot built with FastAPI, LangChain, Hugging Face Qwen, sentence-transformers, and FAISS.

Features

Product recommendation based on user concerns.

Product-specific questions such as ingredients, usage, benefits, and warnings.

Semantic + keyword product matching.

Relevance filtering for unrelated questions.

Safety checking before recommendations.

Conversation sessions through the FastAPI backend.

Web interface served through FastAPI.

Project Structure

guttify-chatbot/
│
├── app.py
├── guttify_chatbot.py
├── recommendation_engine.py
├── safety_checker.py
├── gibberish_checker.py
├── products.json
├── Pipfile
├── requirements.txt
│
├── static/
│   ├── index.html
│   ├── app.js
│   └── style.css
│
└── data/
    └── reference/product documents

Requirements

Python 3.10+

Hugging Face API token

Internet connection for Hugging Face inference

Git

Installation

1. Clone the repository

git clone <YOUR_GITHUB_REPOSITORY_URL>
cd <YOUR_REPOSITORY_FOLDER>

2. Create and activate a virtual environment

Windows PowerShell:

python -m venv env
.\env\Scripts\Activate.ps1

Or activate an existing environment:

.\env\Scriptsctivate

3. Install dependencies

pip install -r requirements.txt

If you need to create requirements.txt from the working environment:

pip freeze > requirements.txt

Environment Variables

Create a .env file in the project root:

HF_TOKEN=your_huggingface_token

Do not commit .env to GitHub.

Recommended .gitignore:

.env
env/
.venv/
__pycache__/
*.pyc

Run Locally

Start the FastAPI server:

uvicorn app:app --reload

Then open:

http://127.0.0.1:8000

Example Questions

Digest Boost

I have constipation.
I feel bloated.
My bowel movements are irregular.

Acid Ease

I have acidity.
I have heartburn.
I experience acid reflux.

Liver Lift

I want liver support.
I feel tired and sluggish.

Piles Pure

I have piles.
I have hemorrhoid discomfort.
I have pain and swelling from piles.

Apple Active

I want weight management support.
I want to improve my metabolism.

Piloease Anal Care Spray

I have anal itching.
I have burning and irritation around the anal area.
What are the ingredients of Piloease Anal Care Spray?
How do I use Piloease?

GloLux GlutaGlow

I have dull skin.
I want skin hydration support.
I want support for skin elasticity.

Boost Vitamin B12

I have low energy.
I have brain fog.
I want vitamin B12 support.

Boost Vitamin D3+

I have low vitamin D.
I don't get much sunlight.
I want support for bone health.

Guttify Poopie

I have hard stools.
My bowel movements are irregular.
I need daily fibre support.
I feel backed up.

Unrelated Questions

Questions outside the Guttify/product domain should be rejected.

Examples:

How was the earth created?
What is my name?
Who is the president of the United States?
Tell me a joke.

Expected behavior:

The information you provided is not relevant to Guttify products.

Recommendation Flow

User
  ↓
FastAPI (app.py)
  ↓
Gibberish Check
  ↓
Product Relevance Check
  ├── Unrelated → NOT_RELEVANT
  ↓
Safety Check
  ├── Needs review → SAFETY_REVIEW
  ↓
Recommendation Engine
  ├── Keyword matching
  └── Semantic matching
  ↓
Relevant Guttify Product
  ↓
Response

API Endpoints

Create Session

POST /api/session

Creates a new chat session.

Chat

POST /api/chat

Example request:

{
  "session_id": "your-session-id",
  "message": "What are the ingredients of the Piloease Anal Care Spray?"
}

Hugging Face Model

The chatbot uses:

Qwen/Qwen2.5-3B-Instruct

through Hugging Face inference.

The embedding model used for product matching is:

sentence-transformers/all-MiniLM-L6-v2

Product Data

Product information is stored in:

products.json

The recommendation engine uses this information for product matching and responses.

Deployment

For a FastAPI cloud deployment, use:

Build command

pip install -r requirements.txt

Start command

uvicorn app:app --host 0.0.0.0 --port $PORT

Add the following environment variable to the hosting platform:

HF_TOKEN

Never put the actual token in the GitHub repository.

Git Commands

git status
git add .
git commit -m "Update Guttify chatbot"
git push

Important Notes

This chatbot is a wellness/product assistant, not a doctor.

It should not diagnose medical conditions.

Product information should come from the configured product data.

Conversation history currently exists only while the application process is running.

LLM responses depend on the availability of the external Hugging Face inference service.
