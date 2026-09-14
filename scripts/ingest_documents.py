"""Load policy PDFs into the vector database. Run this by hand, not from the API.

    uv run python scripts/ingest_documents.py

Re-running replaces everything, so it is safe to run again after editing a PDF or
dropping a new one into data/policies/.

Four steps: find PDFs -> read text -> cut into chunks -> embed and save.
"""

import sys
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.ai.vector_store import build_vector_store
from app.core.config import get_settings

# Roughly a few paragraphs each. Small enough that a retrieved chunk is mostly relevant,
# large enough to keep a policy clause together with the sentence that qualifies it.
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150


def read_pdf_pages(path: Path) -> list[Document]:
    """Turn one PDF into one Document per page, tagged with where it came from."""
    reader = PdfReader(str(path))
    pages: list[Document] = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue  # image-only page, nothing to embed
        pages.append(
            Document(
                page_content=text,
                metadata={"source_file": path.name, "page": page_number},
            )
        )
    return pages


def main() -> None:
    settings = get_settings()
    documents_dir = Path(settings.documents_dir)

    pdf_paths = sorted(documents_dir.glob("*.pdf"))
    if not pdf_paths:
        print(f"No PDFs found in {documents_dir.resolve()}")
        sys.exit(1)

    print(f"Found {len(pdf_paths)} PDF(s) in {documents_dir}:")
    for path in pdf_paths:
        print(f"  - {path.name}")

    # Steps 1 and 2: read every page of every PDF.
    pages: list[Document] = []
    for path in pdf_paths:
        pages.extend(read_pdf_pages(path))
    print(f"\nRead {len(pages)} page(s) with text.")

    if not pages:
        print("No extractable text found. Are these scanned images rather than text PDFs?")
        sys.exit(1)

    # Step 3: cut pages into overlapping chunks. The overlap matters: without it, a
    # sentence split across a boundary loses the context that made it meaningful.
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        add_start_index=True,
    )
    chunks = splitter.split_documents(pages)
    print(f"Split into {len(chunks)} chunk(s).")

    # Step 4: embed and store. The collection is dropped first so that re-running after
    # editing a PDF does not leave stale copies of the old text behind.
    print("\nEmbedding and saving (this calls Gemini, may take a moment)...")
    store = build_vector_store(settings)
    store.delete_collection()
    store.create_collection()
    store.add_documents(chunks)

    print(f"\nDone. {len(chunks)} chunk(s) stored in '{settings.vector_collection_name}'.")


if __name__ == "__main__":
    main()
