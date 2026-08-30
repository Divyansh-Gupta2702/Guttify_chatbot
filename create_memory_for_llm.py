"""Build a FAISS vector store from PDF documents for Guttify's RAG pipeline."""
from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

DATA_PATH = "data/"
DB_FAISS_PATH = "vectorstore/db_faiss"


def load_pdf_files(data_path):
    loader = DirectoryLoader(data_path, glob="*.pdf", loader_cls=PyPDFLoader)
    return loader.load()


def create_chunks(documents, chunk_size=500, chunk_overlap=50):
    splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return splitter.split_documents(documents)


def get_embedding_model():
    return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")


def build_vector_store():
    documents = load_pdf_files(DATA_PATH)
    text_chunks = create_chunks(documents)
    embedding_model = get_embedding_model()

    db = FAISS.from_documents(text_chunks, embedding_model)
    db.save_local(DB_FAISS_PATH)
    return db


if __name__ == "__main__":
    build_vector_store()
