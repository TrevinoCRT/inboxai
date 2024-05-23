import os
import openai
from google.cloud import storage
from loguru import logger

def authenticate_gcs(credentials_path):
    try:
        storage_client = storage.Client.from_service_account_json(credentials_path)
        logger.success("Authenticated with Google Cloud Storage")
        return storage_client
    except Exception as e:
        logger.error(f"GCS authentication failed: {e}")
        return None

def download_pdfs_from_gcs(storage_client, bucket_name, sub_folder, local_dir):
    bucket = storage_client.bucket(bucket_name)
    blobs = bucket.list_blobs(prefix=f"drumbeatpdfs/{sub_folder}/")
    for blob in blobs:
        if blob.name.endswith(".pdf"):
            destination_file = os.path.join(local_dir, blob.name.split("/")[-1])
            logger.info(f"Downloading {blob.name} to {destination_file}")
            blob.download_to_filename(destination_file)
            logger.info(f"Downloaded {blob.name} to {destination_file}")

def create_and_upload_to_vector_store(file_paths, vector_store_name):
    try:
        vector_store = openai.Client().beta.vector_stores.create(name=vector_store_name)
        logger.info(f"Created vector store: {vector_store.id}")

        for file_path in file_paths:
            with open(file_path, "rb") as f:
                file = openai.Client().files.create(file=f, purpose="assistants")
                openai.Client().beta.vector_stores.files.create_and_poll(
                    vector_store_id=vector_store.id, file_id=file.id
                )
                logger.info(f"Uploaded {file_path} to vector store")

        return vector_store.id
    except Exception as e:
        logger.error(f"Error creating or uploading to vector store: {e}")
        return None

def update_assistant_with_vector_store(assistant_id, vector_store_id):
    try:
        openai.Client().beta.assistants.update(
            assistant_id=assistant_id,
            tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}}
        )
        logger.success("Assistant updated with vector store")
    except Exception as e:
        logger.error(f"Failed to update assistant: {e}")

def main():
    PROJECT_ID = "openai-418007"
    LOCATION = "us-central1"
    GCS_BUCKET_DOCS = "openai-418007-me-bucket"
    logger.debug(f"Project ID: {PROJECT_ID}, Location: {LOCATION}, GCS Bucket: {GCS_BUCKET_DOCS}")
    # Set your Google Cloud API key
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "openai-418007-e93119e8b4d3.json"
    logger.info("Google Cloud API key set successfully")
    assistant_id = "asst_a9OH5oxmowHxHO3c6oUxamQn"  # Replace with your assistant ID
    # Authenticate with GCS
    storage_client = authenticate_gcs(credentials_path="openai-418007-e93119e8b4d3.json")
    if not storage_client:
        return  # Exit if authentication fails
    # Define sub-folders within the GCS bucket
    sub_folders = [
        "Cobrand",
        "Cohesive_Infrastructure",
        "Data_Center_Transformation",
        "Infrastructure",
        "Next_Generation_Payments",
        "Price_Value",
        "Pricing",
        "Shared_Services",
        "Stores_Digital_Marketing_EPS_Customer_Service",
        "Stores_Digital_Marketing_ETCC",
        "Supply_Chain_Merch",
        "Technical_Project_Management_Stores_and_Infra",
    ]
    logger.info("Sub-folders defined for processing")
    # Sub-folder Selection
    print("Select the folder to process documents for:")
    for i, folder in enumerate(sub_folders, 1):
        print(f"[{i}] {folder.replace('_', ' ')}")
    folder_choice = int(input("Enter your choice: ")) - 1
    selected_folder = sub_folders[folder_choice]

    # Download PDFs from GCS
    local_dir = "downloaded_pdfs"
    os.makedirs(local_dir, exist_ok=True)
    download_pdfs_from_gcs(storage_client, GCS_BUCKET_DOCS, selected_folder, local_dir)

    # Create and Upload to Vector Store 
    file_paths = [os.path.join(local_dir, f) for f in os.listdir(local_dir) if f.endswith(".pdf")]
    vector_store_name = f"drumbeat_{selected_folder}" 
    vector_store_id = create_and_upload_to_vector_store(file_paths, vector_store_name) 
    if not vector_store_id:
        return  # Exit if vector store creation or upload fails 

    # Update Assistant with Vector Store
    update_assistant_with_vector_store(assistant_id, vector_store_id) 