import streamlit as st
import time
from src.processor import PDFProcessor
from src.embedding import EmbeddingManager
from src.chat import ChatManager
from src.config import Config
import json
from langchain_core.documents import Document

st.set_page_config(page_title="CiteLens | PDF RAG Assistant", page_icon="📚", layout="wide")

def initialize_session_state():
    """
    Initialize the Streamlit session state with the required components.
    Creates instances of the processor, embedding manager, and chat manager.
    """
    if "processor" not in st.session_state:
        st.session_state.processor = PDFProcessor()
        
    if "embedding_manager" not in st.session_state:
        st.session_state.embedding_manager = EmbeddingManager()
        
    if "chat_manager" not in st.session_state:
        # Check if API key is available
        if not Config.is_valid():
            st.error("Missing Gemini API key. Set GEMINI_API_KEY in your local .env file or in Streamlit Community Cloud → App settings → Secrets.")
            return False
            
        st.session_state.chat_manager = ChatManager(Config.GOOGLE_API_KEY)
        
    if "messages" not in st.session_state:
        st.session_state.messages = []
        
    if "documents" not in st.session_state:
        st.session_state.documents = []
        
    return True

def process_documents(uploaded_files):
    """
    Process the uploaded PDF documents.
    """
    try:
        with st.spinner("Processing documents..."):
            all_documents = []
            
            for file in uploaded_files:
                # Process each document using LangChain pipeline
                documents = st.session_state.processor.process_document(file)
                all_documents.extend(documents)
                
            # Store processed documents in session state
            st.session_state.documents = all_documents

            if not all_documents:
                st.warning("No text chunks were extracted. Check OCR/Tesseract installation for scanned PDFs.")
                return False

            # Create embeddings for the documents
            success = st.session_state.embedding_manager.create_embeddings(all_documents)
            
            if success:
                # Connect the retriever to the chat manager
                st.session_state.chat_manager.set_retriever(
                    st.session_state.embedding_manager.retriever
                )
                st.success(f"Successfully processed {len(all_documents)} document chunks!")
                return True
            else:
                st.error("Failed to create embeddings.")
                return False
                
    except Exception as e:
        st.error(f"Error processing documents: {str(e)}")
        return False

def main():
    """
    Main application function.
    """
    # Initialize session state
    if not initialize_session_state():
        return
    
    st.title("📚 CiteLens")
    st.caption("Ask questions about your PDFs and inspect the source passages behind each answer.")
    st.caption("Maintained by Govind Telang")
    st.info("Getting started: upload one or more PDFs in the sidebar, select **Process Documents**, then ask a question below.")
    
    # Sidebar for document upload and controls
    with st.sidebar:
        st.header("Upload Documents")
        uploaded_files = st.file_uploader(
            "Upload PDF files", 
            type=['pdf'], 
            accept_multiple_files=True
        )
        
        if uploaded_files:
            process_button = st.button("Process Documents")
            if process_button:
                process_documents(uploaded_files)
                
        if st.session_state.documents:
            st.success(f"{len(st.session_state.documents)} chunks in memory")
            
            # Add a button to clear the conversation history
            if st.button("Clear Conversation"):
                st.session_state.messages = []
                st.session_state.chat_manager.reset_conversation()
                # FIXED HERE:
                st.rerun() 
            
            # Add a button to clear file chunks
            if st.button("Clear File Chunks"):
                st.session_state.documents = []
                if hasattr(st.session_state.embedding_manager, 'clear_embeddings'):
                    st.session_state.embedding_manager.clear_embeddings()
                st.session_state.messages = []
                st.session_state.chat_manager.clear_retriever()
                st.rerun()
    
    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    # Chat input
    if query := st.chat_input("Ask your question"):
        # Add user message to chat
        st.session_state.messages.append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.write(query)

        # Check if documents have been uploaded and processed
        if not st.session_state.documents:
            with st.chat_message("assistant"):
                st.write("Please upload and process PDF documents first!")
            st.session_state.messages.append({"role": "assistant", "content": "Please upload and process PDF documents first!"})
            return

        # Generate and display assistant response
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                # If using direct retriever-based approach
                if hasattr(st.session_state.embedding_manager, 'retriever') and st.session_state.embedding_manager.retriever:
                    # Using LangChain's conversational retrieval chain
                    response = st.session_state.chat_manager.generate_response(query, [])
                else:
                    # Fallback to manual retrieval and response generation
                    relevant_docs = st.session_state.embedding_manager.search(query)
                    response = st.session_state.chat_manager.generate_response(query, relevant_docs)
                
                answer = ""
                sources = []

                # If result is a string that encodes JSON, try to parse it
                if isinstance(response, str):
                    try:
                        parsed = json.loads(response)
                        if isinstance(parsed, dict) and ("answer" in parsed or "sources" in parsed):
                            response = parsed
                    except Exception:
                        pass

                if isinstance(response, dict):
                    answer = response.get("answer", "")
                    sources = response.get("sources", []) or []
                else:
                    answer = str(response)

                st.write(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})

                # Group retrieved evidence by PDF and page.
                # Keep all retrieved passages for the model, but present
                # passages from the same page together in the UI.
                evidence_by_page = {}

                for src in sources:
                    if not isinstance(src, dict):
                        continue

                    md = src.get("metadata", {}) or {}
                    source_name = md.get("source") or "unknown"
                    page = md.get("page") or "?"
                    key = (source_name, page)
                    snippet = src.get("text")

                    if key not in evidence_by_page:
                        evidence_by_page[key] = {
                            "metadata": dict(md),
                            "snippets": [],
                            "bboxes": [],
                            "chunk_ids": [],
                        }

                    entry = evidence_by_page[key]

                    if snippet and snippet not in entry["snippets"]:
                        entry["snippets"].append(snippet)

                    chunk_id = md.get("chunk_id")
                    if (
                        chunk_id is not None
                        and chunk_id not in entry["chunk_ids"]
                    ):
                        entry["chunk_ids"].append(chunk_id)

                    for bbox in md.get("bboxes", []) or []:
                        try:
                            bbox_key = tuple(float(v) for v in bbox)
                        except (TypeError, ValueError):
                            continue

                        if bbox_key not in entry["bboxes"]:
                            entry["bboxes"].append(bbox_key)

                    for field in (
                        "page_image",
                        "page_image_width",
                        "page_image_height",
                    ):
                        if not entry["metadata"].get(field) and md.get(field):
                            entry["metadata"][field] = md[field]

                if evidence_by_page:
                    st.caption(
                        "Retrieved evidence grouped by PDF page. "
                        "Check the passages against the answer."
                    )

                for i, ((source_name, page), entry) in enumerate(
                    evidence_by_page.items(), start=1
                ):
                    md = entry["metadata"]
                    snippets = entry["snippets"]
                    bboxes = entry["bboxes"]
                    page_image_b64 = md.get("page_image")
                    img_w = md.get("page_image_width")
                    img_h = md.get("page_image_height")

                    passage_count = len(snippets)
                    passage_label = (
                        "passage" if passage_count == 1 else "passages"
                    )

                    header = (
                        f"Evidence {i}: {source_name} "
                        f"(page {page}; {passage_count} {passage_label})"
                    )

                    with st.expander(header, expanded=False):
                        for j, snippet in enumerate(snippets, start=1):
                            st.markdown(f"**Passage {j}**")
                            st.markdown(snippet)

                        if page_image_b64 and img_w and img_h:
                            boxes_html = ""

                            for bbox in bboxes:
                                try:
                                    x0, y0, x1, y1 = bbox

                                    left = (x0 / img_w) * 100
                                    top = (y0 / img_h) * 100
                                    width = ((x1 - x0) / img_w) * 100
                                    height = ((y1 - y0) / img_h) * 100

                                    boxes_html += (
                                        "<div style='position:absolute;"
                                        f"left:{left}%;top:{top}%;"
                                        f"width:{width}%;height:{height}%;"
                                        "border:3px solid "
                                        "rgba(255,0,0,0.8);"
                                        "box-sizing:border-box;'></div>"
                                    )

                                except (TypeError, ValueError):
                                    continue

                            html = f"""
                            <div style='position:relative;
                                        display:inline-block;
                                        border:1px solid #eee'>
                              <img
                                src='data:image/png;base64,{page_image_b64}'
                                style='max-width:600px;
                                       height:auto;
                                       display:block'
                              />
                              <div style='position:absolute;
                                          left:0;
                                          top:0;
                                          width:100%;
                                          height:100%;
                                          pointer-events:none;'>
                                {boxes_html}
                              </div>
                            </div>
                            """

                            st.components.v1.html(html, height=450)

                        else:
                            st.caption(
                                f"Source: {source_name} · "
                                f"Page: {page} · "
                                f"Chunk IDs: {entry['chunk_ids']}"
                            )

if __name__ == "__main__":
    main()