# MedGuide AI — Ingestion & Knowledge Base Guide 📚

This guide details the document processing, semantic chunking, embedding generation, and vector retrieval architecture that powers the **Retrieval-Augmented Generation (RAG)** pipeline in **MedGuide AI**.

---

## 1. Pipeline Overview

```
 [ Clinical PDF Reference ] (e.g. data/medical_book.pdf)
             │
             ▼
 ┌───────────────────────────────────────────────┐
 │          PyMuPDF Document Parser              │
 │  - Extracts raw page text page-by-page        │
 └───────────────────────┬───────────────────────┘
                         │
                         ▼
 ┌───────────────────────────────────────────────┐
 │       Sliding Window Text Chunker             │
 │  - Size: 1100 characters                      │
 │  - Overlap: 180 characters                    │
 │  - Whitespace & format normalization          │
 └───────────────────────┬───────────────────────┘
                         │
                         ▼
 ┌───────────────────────────────────────────────┐
 │       SHA-256 Deduplication Generator         │
 │  - Hash: sha256(filename + page + part + text)│
 │  - Prevents duplicate vector index records    │
 └───────────────────────┬───────────────────────┘
                         │
                         ▼
 ┌───────────────────────────────────────────────┐
 │          Embeddings Batch Engine              │
 │  - Batches 50 chunks per API request          │
 │  - Model: text-embedding-3-small (1536 dim)   │
 └───────────────────────┬───────────────────────┘
                         │
                         ▼
 ┌───────────────────────────────────────────────┐
 │    Pinecone Serverless Vector Store           │
 │  - Cosine similarity metric                   │
 │  - Metadata: {page, text, file}               │
 └───────────────────────────────────────────────┘
```

---

## 2. Ingestion CLI (`ingest.py`)

To index a medical reference encyclopedia into your Pinecone vector database:

```bash
# Ingest default reference encyclopedia:
python ingest.py --pdf data/medical_book.pdf

# Ingest custom institutional clinical guidance PDF:
python ingest.py --pdf path/to/your_hospital_guidelines.pdf
```

### Ingestion Performance & Deduplication
- **Batching:** Vector upserts are batched in groups of 50 to minimize HTTP request overhead and prevent rate limit exhaustion.
- **Deterministic ID Generation:** Each chunk receives an ID computed via:
  ```python
  key = hashlib.sha256(f"{pdf.name}:{page_number}:{part}:{content}".encode()).hexdigest()
  ```
  If you re-run `ingest.py`, existing chunks are safely overwritten without duplicating records or bloating vector storage.

---

## 3. Retrieval Architecture (`app/knowledge.py`)

When a patient query is submitted to the LangGraph agent:

1. **Query Vectorization:** The user's sanitized question (plus any objective visual features from an attached image) is vectorized using the active embedding model.
2. **Pinecone Vector Search:** The query vector is matched against the Pinecone index using cosine similarity:
   ```python
   results = index.query(vector=query_vector, top_k=4, include_metadata=True)
   ```
3. **Thresholding & Filtering:**
   - If the top result score $\ge 0.62$, the knowledge base is considered sufficient and cited directly.
   - If the top score $< 0.62$, the LangGraph state machine automatically triggers a fallback route to **Tavily Live Web Search** to find authoritative, up-to-date clinical guidance.

---

## 4. Citation Protocol

Every retrieved excerpt retains precise metadata:
- **`file`:** Originating PDF document name.
- **`page`:** Exact source page number in the medical reference book.
- **`score`:** Cosine similarity relevance score (0.000 to 1.000).

Responses display verifiable citations directly in the web UI:
> `[PDF p.142]` or `CDC Clinical Guidance (https://cdc.gov/...)`
