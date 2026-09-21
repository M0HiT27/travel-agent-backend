"""One-off CLI: chunk and embed a policy PDF into `document_chunks`.

Each domain owns its own PDF and runs this independently -- it is not part of the
request-serving app, and does not touch other domains' rows (`domain` scopes it).

Usage:
    uv run python -m app.ingestion.pdf_loader --domain bus --file policy_docs/bus_policy.pdf
"""

import argparse
import sys
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.llm.embeddings import get_embeddings
from app.vectorstores.pgvector_store import add_chunks

_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 150


def load_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


def chunk_text(text: str) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=_CHUNK_SIZE, chunk_overlap=_CHUNK_OVERLAP
    )
    return [chunk.strip() for chunk in splitter.split_text(text) if chunk.strip()]


def ingest(*, domain: str, file: Path, source: str | None = None) -> int:
    """Chunk, embed and store `file` under `domain`. Returns the number of chunks stored."""
    text = load_pdf_text(file)
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError(f"No extractable text found in {file}")

    settings = get_settings()
    embeddings = get_embeddings(settings).embed_documents(chunks)

    with SessionLocal() as db:
        add_chunks(
            db,
            domain=domain,
            source=source or file.name,
            contents=chunks,
            embeddings=embeddings,
        )
        db.commit()

    return len(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True, help='e.g. "bus", "hotel", "flight"')
    parser.add_argument("--file", required=True, type=Path, help="Path to the PDF to ingest")
    parser.add_argument(
        "--source",
        default=None,
        help="Display name for citations (defaults to the file name)",
    )
    args = parser.parse_args()

    if not args.file.exists():
        print(f"File not found: {args.file}", file=sys.stderr)
        raise SystemExit(1)

    count = ingest(domain=args.domain, file=args.file, source=args.source)
    print(f"Stored {count} chunk(s) for domain={args.domain!r} from {args.file}")


if __name__ == "__main__":
    main()
