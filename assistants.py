import os
import json
import asyncio
from openai import AsyncOpenAI
from dotenv import load_dotenv
import io
from google.cloud import storage
from alive_progress import alive_bar
from logger_config import logger
from gmailapi import fetch_unread_emails, fetch_email_content, draft_email, send_email, check_saved_access_token, start_oauth_and_server, get_events_for_next_10_days
# Load environment variables
load_dotenv()
assistant_id = "asst_9Ktnx0WWDOswzeL1FvDqOWRF"
# Initialize OpenAI API client
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

async def execute_function(function_name, arguments, from_user):
    logger.debug(f"Executing function: {function_name} with arguments: {arguments} from user: {from_user}")
    
    if function_name in ['fetch_unread_emails', 'fetch_email_content', 'draft_email', 'send_email', 'get_events_for_next_10_days']:
        logger.debug("Checking for saved access token...")
        token = await check_saved_access_token()
        if not token:
            logger.info("No access token found. Initiating OAuth flow.")
            await start_oauth_and_server()
            logger.debug("OAuth flow initiated. Waiting for token...")
            # Wait until the credentials file exists and has valid credentials
            while not os.path.exists('gmail-api-credentials.json'):
                logger.debug("Checking for existence of credentials file every 5 seconds.")
                await asyncio.sleep(5)  # Check every 5 seconds if the token file is available
            # After the file exists, check for valid credentials
            token = await check_saved_access_token()
            while not token:
                logger.debug("Waiting for valid credentials...")
                await asyncio.sleep(5)  # Check every 5 seconds for valid credentials
                token = await check_saved_access_token()
        
        if token:
            logger.debug("Valid access token found. Proceeding with API calls.")
            if function_name == 'fetch_unread_emails':
                logger.debug("Fetching unread emails...")
                emails_info = await fetch_unread_emails()
                logger.debug(f"Unread emails fetched: {emails_info}")
                return emails_info  # Directly return the result without additional await
            elif function_name == 'fetch_email_content':
                email_id = arguments.get("email_id")
                logger.debug(f"Fetching content for email ID: {email_id}")
                email_content = await fetch_email_content(email_id)
                logger.debug(f"Email content fetched: {email_content}")
                return email_content
            elif function_name == 'draft_email':
                to = arguments.get("to")
                subject = arguments.get("subject")
                message_text = arguments.get("message_text")
                logger.debug(f"Drafting email to: {to}, subject: {subject}")
                draft_id = await draft_email(to, subject, message_text)
                logger.debug(f"Email drafted with ID: {draft_id}")
                return draft_id
            elif function_name == 'send_email':
                draft_id = arguments.get("draft_id")
                logger.debug(f"Sending email with draft ID: {draft_id}")
                sent_id = await send_email(draft_id)
                logger.debug(f"Email sent with ID: {sent_id}")
                return sent_id
            elif function_name == 'get_events_for_next_10_days':
                logger.debug("Fetching events for the next 10 days...")
                events = await get_events_for_next_10_days()
                logger.debug(f"Events fetched: {events}")
                return events
        else:
            logger.error("Failed to obtain valid access token after waiting.")
            return {"status": "error", "message": "Failed to obtain valid access token after waiting."}
    else:
        logger.error(f"Function not recognized: {function_name}")
        return {"status": "error", "message": "Function not recognized"}
    
global_thread_id = None
async def process_thread_with_assistant(query, assistant_id, model="gpt-3.5-turbo-1106", from_user=None):
    global global_thread_id
    response_texts = []
    response_files = []
    in_memory_files = []
    try:
        if not global_thread_id:
            logger.debug("Creating a new thread for the user query...")
            thread = await client.beta.threads.create()
            global_thread_id = thread.id
            logger.debug(f"New thread created with ID: {global_thread_id}")
        
        logger.debug("Adding the user query as a message to the thread...")
        await client.beta.threads.messages.create(
            thread_id=global_thread_id,
            role="user",
            content=query
        )
        logger.debug("User query added to the thread.")

        logger.debug("Creating a run to process the thread with the assistant...")
        run = await client.beta.threads.runs.create(
            thread_id=global_thread_id,
            assistant_id=assistant_id,
            model=model
        )
        logger.debug(f"Run created with ID: {run.id}")

        while True:
            logger.debug("Initiating status check for the run...")
            try:
                run_status = await client.beta.threads.runs.retrieve(
                    thread_id=global_thread_id,
                    run_id=run.id
                )
                logger.debug(f"API Call: Retrieve run status for run_id={run.id} in thread_id={global_thread_id}")
                logger.debug(f"Response: Run status retrieved successfully with status: {run_status.status}")
            except Exception as e:
                logger.error(f"Failed to retrieve run status: {e}")
                break

            if run_status.status == "requires_action":
                logger.debug("Run requires action. Preparing to execute the specified function...")
                try:
                    tool_call = run_status.required_action.submit_tool_outputs.tool_calls[0]
                    function_name = tool_call.function.name
                    arguments = json.loads(tool_call.function.arguments)
                    logger.debug(f"Function to execute: {function_name} with arguments: {arguments}")
                except Exception as e:
                    logger.error(f"Error parsing required action details: {e}")
                    continue

                try:
                    function_output = await execute_function(function_name, arguments, from_user)
                    function_output_str = json.dumps(function_output)
                    logger.debug(f"Function {function_name} executed. Output: {function_output_str}")
                except Exception as e:
                    logger.error(f"Error executing function {function_name}: {e}")
                    continue

                try:
                    logger.debug("Preparing to submit tool outputs to the run...")
                    response = await client.beta.threads.runs.submit_tool_outputs(
                        thread_id=global_thread_id,
                        run_id=run.id,
                        tool_outputs=[{
                            "tool_call_id": tool_call.id,
                            "output": function_output_str
                        }]
                    )
                    logger.debug(f"Tool outputs successfully submitted. Response: {response}")
                except Exception as e:
                    logger.error(f"Failed to submit tool outputs: {e}")
                    logger.debug(f"Exception details: {e.__class__.__name__}: {str(e)}")

            elif run_status.status in ["completed", "failed", "cancelled"]:
                logger.debug(f"Run status is {run_status.status}. Initiating fetch for the latest assistant message...")
                try:
                    messages_response = await client.beta.threads.messages.list(
                        thread_id=global_thread_id,
                        order="desc"
                    )
                    logger.debug(f"API Call: List messages for thread in descending order. Response: {messages_response}")
                    latest_assistant_message = next((message for message in messages_response.data if message.role == "assistant"), None)
                    if latest_assistant_message:
                        logger.debug(f"Latest assistant message retrieved: {latest_assistant_message.content}")
                    else:
                        logger.debug("No assistant messages found.")
                except Exception as e:
                    logger.error(f"Failed to fetch messages: {e}")
                    logger.debug(f"Exception details: {e.__class__.__name__}: {str(e)}")
                    break
                
                if latest_assistant_message:
                    for content in latest_assistant_message.content:
                        if content.type == "text":
                            text_value = content.text.value
                            # Check for annotations and replace them
                            for annotation in content.text.annotations:
                                if annotation.type == "file_citation":
                                    cited_file_response = await client.files.retrieve(annotation.file_citation.file_id)
                                    citation_text = f"[Cited from {cited_file_response.filename}]"
                                    text_value = text_value.replace(annotation.text, citation_text)
                                    logger.debug(f"File citation replaced in text. Original: {annotation.text}, New: {citation_text}")
                                elif annotation.type == "file_path":
                                    file_info_response = await client.files.retrieve(annotation.file_path.file_id)
                                    download_link = f"<https://platform.openai.com/files/{file_info_response.id}|Download {file_info_response.filename}>"
                                    text_value = text_value.replace(annotation.text, download_link)
                                    logger.debug(f"File path link replaced in text. Original: {annotation.text}, New: {download_link}")
                            response_texts.append(text_value)
                        elif content.type == "file":
                            file_id = content.file.file_id
                            file_mime_type = content.file.mime_type
                            response_files.append((file_id, file_mime_type))

                    for file_id, mime_type in response_files:
                        try:
                            logger.debug(f"Retrieving content for file ID: {file_id} with MIME type: {mime_type}")
                            file_response = await client.files.content(file_id)
                            file_content = file_response.content if hasattr(file_response, 'content') else file_response
                            logger.debug(f"File content retrieved for file ID: {file_id}. Content length: {len(file_content)}")

                            # Determine file extension based on MIME type
                            extensions = {
                                "text/x-c": ".c", "text/x-csharp": ".cs", "text/x-c++": ".cpp",
                                "application/msword": ".doc", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                                "text/html": ".html", "text/x-java": ".java", "application/json": ".json",
                                "text/markdown": ".md", "application/pdf": ".pdf", "text/x-php": ".php",
                                "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
                                "text/x-python": ".py", "text/x-script.python": ".py", "text/x-ruby": ".rb",
                                "text/x-tex": ".tex", "text/plain": ".txt", "text/css": ".css",
                                "text/javascript": ".js", "application/x-sh": ".sh", "application/typescript": ".ts",
                                "application/csv": ".csv", "image/jpeg": ".jpeg", "image/gif": ".gif",
                                "image/png": ".png", "application/x-tar": ".tar",
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
                                "application/xml": "text/xml", "application/zip": ".zip"
                            }
                            file_extension = extensions.get(mime_type, ".bin")  # Default to .bin if unknown
                            logger.debug(f"File extension determined: {file_extension} for MIME type: {mime_type}")

                            # Save the file locally
                            local_file_path = f"./downloaded_file_{file_id}{file_extension}"
                            with open(local_file_path, "wb") as local_file:
                                local_file.write(file_content)
                            logger.debug(f"File saved locally at {local_file_path}")

                        except Exception as e:
                            logger.error(f"Failed to retrieve content for file ID: {file_id}. Error: {e}")
                            logger.debug(f"Exception details: {e.__class__.__name__}: {str(e)}")

                break
            await asyncio.sleep(1)

        return {"text": response_texts, "in_memory_files": in_memory_files}

    except Exception as e:
        logger.error(f"An error occurred: {e}")
        logger.debug(f"Exception details: {e.__class__.__name__}: {str(e)}")
        return {"text": [], "in_memory_files": []}


def authenticate_gcs(credentials_path):
    try:
        storage_client = storage.Client.from_service_account_json(credentials_path)
        logger.success("Authenticated with Google Cloud Storage")
        return storage_client
    except Exception as e:
        logger.error(f"GCS authentication failed: {e}")
        return None

def download_pdfs_from_gcs(storage_client, bucket_name, sub_folder, local_dir):
    logger.debug(f"Initiating download_pdfs_from_gcs with bucket_name: {bucket_name}, sub_folder: {sub_folder}, local_dir: {local_dir}")
    try:
        bucket = storage_client.bucket(bucket_name)
        logger.debug(f"Accessed bucket: {bucket_name}")
    except Exception as e:
        logger.error(f"Error accessing bucket {bucket_name}: {e}")
        return

    try:
        blobs = bucket.list_blobs(prefix=f"drumbeatpdfs/{sub_folder}/")
        blob_list = [blob for blob in blobs if blob.name.endswith(".pdf")]
        logger.info(f"Found {len(blob_list)} PDFs in {sub_folder} to download.")
    except Exception as e:
        logger.error(f"Error listing blobs in {bucket_name}/{sub_folder}: {e}")
        return

    with alive_bar(len(blob_list), title='Downloading PDFs') as bar:
        for blob in blob_list:
            try:
                destination_file = os.path.join(local_dir, blob.name.split("/")[-1])
                logger.debug(f"Preparing to download {blob.name} to {destination_file}")
                blob.download_to_filename(destination_file)
                logger.info(f"Successfully downloaded {blob.name} to {destination_file}")
                bar()
            except Exception as e:
                logger.error(f"Failed to download {blob.name} to {destination_file}: {e}")

async def create_and_upload_to_vector_store(file_paths, vector_store_name):
    logger.debug(f"Initiating create_and_upload_to_vector_store with vector_store_name: {vector_store_name} and file_paths: {file_paths}")
    try:
        vector_store = await client.beta.vector_stores.create(name=vector_store_name)
        logger.info(f"Vector store created with ID: {vector_store.id}")

        file_streams = [open(path, "rb") for path in file_paths]
        try:
            file_batch = await client.beta.vector_stores.file_batches.upload_and_poll(
                vector_store_id=vector_store.id, files=file_streams
            )
        finally:
            for f in file_streams:
                f.close()

        logger.info(f"File batch status: {file_batch.status}")
        logger.info(f"File counts in batch: {file_batch.file_counts}")

        return vector_store.id
    except AttributeError as e:
        logger.error(f"Failed to create or upload to vector store: {e}")
        return None

async def update_assistant_with_vector_store(assistant_id, vector_store_id):
    try:
        await client.beta.assistants.update(
            assistant_id=assistant_id,
            tool_resources={"file_search": {"vector_store_ids": [vector_store_id]}},
        )
        logger.success("Assistant updated with vector store")
    except Exception as e:
        logger.error(f"Failed to update assistant: {e}")

async def main():
    PROJECT_ID = "openai-418007"
    LOCATION = "us-central1"
    GCS_BUCKET_DOCS = "openai-418007-me-bucket"
    logger.debug(f"Project ID: {PROJECT_ID}, Location: {LOCATION}, GCS Bucket: {GCS_BUCKET_DOCS}")
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "openai-418007-e93119e8b4d3.json"
    logger.info("Google Cloud API key set successfully")
    assistant_id = "asst_9Ktnx0WWDOswzeL1FvDqOWRF"
    storage_client = authenticate_gcs(credentials_path="openai-418007-e93119e8b4d3.json")
    if not storage_client:
        return

    print("Do you want to add files to an existing vector store or create a new one?")
    print("[1] Add to existing vector store")
    print("[2] Create new vector store")
    vector_store_choice = int(input("Enter your choice: "))

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
    print("Select the folder to process documents for:")
    for i, folder in enumerate(sub_folders, 1):
        print(f"[{i}] {folder.replace('_', ' ')}")
    folder_choice = int(input("Enter your choice: ")) - 1
    selected_folder = sub_folders[folder_choice]

    local_dir = "downloaded_pdfs"
    os.makedirs(local_dir, exist_ok=True)
    download_pdfs_from_gcs(storage_client, GCS_BUCKET_DOCS, selected_folder, local_dir)

    file_paths = [os.path.join(local_dir, f) for f in os.listdir(local_dir) if f.endswith(".pdf")]

    if vector_store_choice == 1:
        vector_store_id = "vs_7HNjrhDESus71F1VeUVHsVgB"
        await add_files_to_existing_vector_store(file_paths, vector_store_id)
    elif vector_store_choice == 2:
        vector_store_name = f"drumbeat_{selected_folder}" 
        vector_store_id = await create_and_upload_to_vector_store(file_paths, vector_store_name)
        if vector_store_id:
            await update_assistant_with_vector_store(assistant_id, vector_store_id)

async def add_files_to_existing_vector_store(file_paths, vector_store_id):
    logger.debug(f"Adding files to existing vector store with ID: {vector_store_id}")
    try:
        file_streams = [open(path, "rb") for path in file_paths]
        try:
            file_batch = await client.beta.vector_stores.file_batches.upload_and_poll(
                vector_store_id=vector_store_id, files=file_streams
            )
            logger.info(f"Files added to vector store ID: {vector_store_id}. Batch status: {file_batch.status}")
        finally:
            for f in file_streams:
                f.close()
    except Exception as e:
        logger.error(f"Failed to add files to existing vector store: {e}")

if __name__ == "__main__":
    asyncio.run(main())