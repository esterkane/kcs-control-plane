# Local Jina Embeddings

This service exposes a local OpenAI-compatible `/v1/embeddings` endpoint backed by
`jinaai/jina-embeddings-v3-hf`.

Notes:

- The model is downloaded on first start and cached in the `huggingface_cache` Docker volume.
- The Hugging Face model is licensed under `CC BY-NC 4.0`; review that before production or commercial use.
- The service keeps the `task` parameter from the request so `retrieval.passage` remains available for duplicate detection.
