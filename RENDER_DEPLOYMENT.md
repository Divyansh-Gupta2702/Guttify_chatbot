# GutGPT — Render Deployment

This package is configured for Render as a Docker Web Service.

## Render settings

- Runtime: Docker
- Dockerfile: `./Dockerfile`
- Docker context: `.`
- Environment variable: `GROQ_API_KEY`

The Dockerfile starts FastAPI with Uvicorn on port `8080` and binds to `0.0.0.0`.

## Important

The live application uses the deterministic product/clinical logic in the Python files and Groq for response generation. The optional offline RAG scripts and their large dependencies are not installed in the production image.

Session state is held in process memory, so restarting the service clears active conversations. Keep the Render service at one instance unless session storage is moved to a shared store.
