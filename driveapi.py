import os
import json
import base64
from logger_config import logger
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from concurrent.futures import ThreadPoolExecutor
import asyncio
import httplib2
from email.message import EmailMessage
import re
import io
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
import googleapiclient

# Constants for Google API
CLIENT_SECRET_FILE = 'client_secret.json'
API_SCOPE = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive']
CREDENTIALS_STORAGE_FILE = 'drive-api-credentials.json'

# Configure logging
httplib2.debuglevel = 4

executor = ThreadPoolExecutor()

async def run_in_executor(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, func, *args)

def start_oauth_flow():
    credentials = None
    if os.path.exists(CREDENTIALS_STORAGE_FILE):
        credentials = Credentials.from_authorized_user_file(CREDENTIALS_STORAGE_FILE, API_SCOPE)
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            from oauth2client.client import flow_from_clientsecrets
            flow = flow_from_clientsecrets(CLIENT_SECRET_FILE, scope=API_SCOPE, redirect_uri='urn:ietf:wg:oauth:2.0:oob')
            auth_uri = flow.step1_get_authorize_url()
            logger.info(f"Please go to this URL and authorize the application: {auth_uri}")
            auth_code = input('Enter the authorization code here: ')
            credentials = flow.step2_exchange(auth_code)
            with open(CREDENTIALS_STORAGE_FILE, 'w') as token:
                token.write(credentials.to_json())
    return credentials

async def start_oauth_and_server():
    return await run_in_executor(start_oauth_flow)

def check_access_token():
    logger.debug("Checking if credentials storage file exists.")
    if os.path.exists(CREDENTIALS_STORAGE_FILE):
        logger.debug("Credentials file found, loading credentials.")
        credentials = Credentials.from_authorized_user_file(CREDENTIALS_STORAGE_FILE, API_SCOPE)
        if credentials and credentials.valid:
            logger.debug("Credentials are valid.")
            return credentials
        elif credentials and credentials.expired and credentials.refresh_token:
            logger.debug("Credentials expired, refreshing token.")
            credentials.refresh(Request())
            with open(CREDENTIALS_STORAGE_FILE, 'w') as token:
                token.write(credentials.to_json())
                logger.debug("Credentials refreshed and saved.")
            return credentials if credentials.valid else None
    logger.debug("Credentials file not found or credentials not valid.")
    return None

async def check_saved_access_token():
    logger.debug("Asynchronously checking saved access token.")
    return await run_in_executor(check_access_token)

def refresh_access_token_sync():
    logger.debug("Synchronously refreshing access token.")
    credentials = check_access_token()
    if credentials and credentials.expired:
        logger.debug("Token expired, refreshing.")
        credentials.refresh(Request())
        with open(CREDENTIALS_STORAGE_FILE, 'w') as token:
            token.write(credentials.to_json())
            logger.debug("Token refreshed and saved.")
        return credentials.token
    logger.debug("No valid credentials available for refresh.")
    return None

async def refresh_access_token():
    logger.debug("Asynchronously refreshing access token.")
    return await run_in_executor(refresh_access_token_sync)

async def list_drive_files():
    credentials = await check_saved_access_token()
    if not credentials:
        logger.error("No valid credentials available for Google Drive access.")
        return []
    service = build('drive', 'v3', credentials=credentials)
    results = service.files().list(
        pageSize=10, fields="nextPageToken, files(id, name)").execute()
    items = results.get('files', [])
    if not items:
        logger.info("No files found in Google Drive.")
        return []
    return items

async def download_drive_file(file_id, file_name):
    credentials = await check_saved_access_token()
    if not credentials:
        logger.error("No valid credentials available for downloading.")
        return None
    service = build('drive', 'v3', credentials=credentials)
    try:
        file = service.files().get(fileId=file_id, fields='mimeType').execute()
    except googleapiclient.errors.HttpError as error:
        logger.error(f"Failed to retrieve file: {error}")
        return None
    mime_type = file.get('mimeType')
    if mime_type.startswith('application/vnd.google-apps'):
        # It's a Google Docs file, needs exporting
        export_mime_types = {
            'application/vnd.google-apps.document': [
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # DOCX
                'application/vnd.oasis.opendocument.text',  # ODT
                'application/rtf',  # RTF
                'application/pdf',  # PDF
                'text/plain',  # TXT
                'application/zip',  # HTML (ZIP)
                'application/epub+zip'  # EPUB
            ],
            'application/vnd.google-apps.spreadsheet': [
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # XLSX
                'application/x-vnd.oasis.opendocument.spreadsheet',  # ODS
                'application/pdf',  # PDF
                'application/zip',  # HTML (ZIP)
                'text/csv',  # CSV
                'text/tab-separated-values'  # TSV
            ],
            'application/vnd.google-apps.presentation': [
                'application/vnd.openxmlformats-officedocument.presentationml.presentation',  # PPTX
                'application/vnd.oasis.opendocument.presentation',  # ODP
                'application/pdf',  # PDF
                'text/plain',  # TXT
                'image/jpeg',  # JPEG
                'image/png',  # PNG
                'image/svg+xml'  # SVG
            ],
            'application/vnd.google-apps.drawing': [
                'application/pdf',  # PDF
                'image/jpeg',  # JPEG
                'image/png',  # PNG
                'image/svg+xml'  # SVG
            ],
            'application/vnd.google-apps.script': [
                'application/vnd.google-apps.script+json'  # JSON
            ]
        }
        if mime_type in export_mime_types:
            # Choose the first available export format for simplicity
            export_mime_type = export_mime_types[mime_type][0]
            request = service.files().export_media(fileId=file_id, mimeType=export_mime_type)
            # Append appropriate file extension based on the document type
            if mime_type == 'application/vnd.google-apps.document':
                file_name += '.docx'
            elif mime_type == 'application/vnd.google-apps.spreadsheet':
                file_name += '.csv'
            elif mime_type == 'application/vnd.google-apps.presentation':
                file_name += '.pptx'
        else:
            logger.error("Unsupported Google Docs type for export.")
            return None
    else:
        # It's a binary file, can be directly downloaded
        request = service.files().get_media(fileId=file_id)
    
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        logger.info("Download %d%%." % int(status.progress() * 100))
    file_name = file_name.replace('/', '_')  # Sanitize file_name to replace slashes with underscores
    with open(file_name, 'wb') as f:
        f.write(fh.getvalue())
    return file_name
