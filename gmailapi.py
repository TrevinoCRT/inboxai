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
from datetime import datetime, timedelta
import pytz
# Constants for Google API
CLIENT_SECRET_FILE = 'client_secret.json'
API_SCOPE = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar'
]
CREDENTIALS_STORAGE_FILE = 'gmail-api-credentials.json'

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

async def fetch_unread_emails():
    logger.debug("Starting the process to fetch priority emails.")
    credentials = await check_saved_access_token()
    if not credentials:
        logger.error("Failed to retrieve valid credentials. Cannot proceed with fetching emails.")
        return []
    logger.debug(f"Credentials obtained: {credentials.token}")
    service = build('gmail', 'v1', credentials=credentials)
    logger.debug("Gmail service instance created successfully.")
    try:
        logger.debug("Attempting to list messages with API call.")
        results = service.users().messages().list(userId='me', labelIds=['INBOX'], q='-in:replies', maxResults=5).execute()
        logger.debug(f"API request sent. Received response: {results}")
    except Exception as e:
        logger.error(f"Failed to fetch messages due to an error: {e}")
        return []
    messages = results.get('messages', [])
    emails_info = []
    logger.debug(f"Total priority messages retrieved: {len(messages)}")
    for msg in messages:
        logger.debug(f"Processing message ID: {msg['id']}")
        try:
            msg_detail = service.users().messages().get(userId='me', id=msg['id'], format='metadata', metadataHeaders=['subject']).execute()
            logger.debug(f"Details fetched for message ID {msg['id']}: {msg_detail}")
            subject_header = next((header['value'] for header in msg_detail['payload']['headers'] if header['name'].lower() == 'subject'), 'No Subject')
            emails_info.append({'id': msg['id'], 'subject': subject_header})
            logger.debug(f"Message ID: {msg['id']} has subject: {subject_header}")
        except Exception as e:
            logger.error(f"Error fetching details for message ID {msg['id']}: {e}")
            continue
    return emails_info

async def fetch_email_content(email_id):
    credentials = await check_saved_access_token()
    if not credentials:
        logger.error("No valid credentials available.")
        return None
    service = build('gmail', 'v1', credentials=credentials)
    try:
        # Fetching metadata with additional headers
        metadata_headers = ['From', 'To', 'Cc', 'Subject', 'Date']
        message = service.users().messages().get(userId='me', id=email_id, format='metadata', metadataHeaders=metadata_headers).execute()
        
        # Extracting email details from headers
        headers = message.get('payload', {}).get('headers', [])
        email_details = {header['name']: header['value'] for header in headers if header['name'] in metadata_headers}
        
        # Returning the snippet and the detailed email headers
        return {
            'snippet': message.get('snippet', 'No snippet available'),
            'email_details': email_details
        }
    except Exception as e:
        logger.error(f"Failed to fetch email content: {e}")
        return None

async def fetch_relevant_emails(max_results=15, include_snippets=True):
    logger.debug("Starting the process to fetch relevant emails.")
    credentials = await check_saved_access_token()
    if not credentials:
        logger.error("Failed to retrieve valid credentials. Cannot proceed with fetching emails.")
        return []
    logger.debug(f"Credentials obtained: {credentials.token}")
    service = build('gmail', 'v1', credentials=credentials)
    logger.debug("Gmail service instance created successfully.")
    try:
        logger.debug("Attempting to list messages with API call.")
        query = '(from:*@kohls.com OR from:*@google.com)'
        results = service.users().messages().list(userId='me', labelIds=['INBOX'], q=query, maxResults=max_results).execute()
        logger.debug(f"API request sent. Received response: {results}")
    except Exception as e:
        logger.error(f"Failed to fetch messages due to an error: {e}")
        return []
    messages = results.get('messages', [])
    emails_info = []
    logger.debug(f"Total relevant messages retrieved: {len(messages)}")
    for msg in messages:
        logger.debug(f"Processing message ID: {msg['id']}")
        try:
            msg_detail = service.users().messages().get(userId='me', id=msg['id'], format='metadata', metadataHeaders=['subject', 'snippet', 'from', 'to', 'date']).execute()
            logger.debug(f"Details fetched for message ID {msg['id']}: {msg_detail}")
            subject_header = next((header['value'] for header in msg_detail['payload']['headers'] if header['name'].lower() == 'subject'), 'No Subject')
            snippet = msg_detail.get('snippet', 'No snippet available') if include_snippets else None
            from_header = next((header['value'] for header in msg_detail['payload']['headers'] if header['name'].lower() == 'from'), 'Unknown Sender')
            to_header = next((header['value'] for header in msg_detail['payload']['headers'] if header['name'].lower() == 'to'), 'Unknown Recipient')
            date_header = next((header['value'] for header in msg_detail['payload']['headers'] if header['name'].lower() == 'date'), 'Unknown Date')
            emails_info.append({'id': msg['id'], 'subject': subject_header, 'snippet': snippet, 'from': from_header, 'to': to_header, 'date': date_header})
            logger.debug(f"Message ID: {msg['id']} has subject: {subject_header}, snippet: {snippet}, from: {from_header}, to: {to_header}, date: {date_header}")
        except Exception as e:
            logger.error(f"Error fetching details for message ID {msg['id']}: {e}")
            continue
    return emails_info

async def fetch_custom_email_content(email_id, metadata_headers=None):
    """
    Fetches email content with customizable metadata headers.
    Args:
        email_id (str): The ID of the email to fetch.
        metadata_headers (list): List of metadata headers to fetch, e.g., ['From', 'To', 'Cc'].

    Returns:
        dict: A dictionary containing the email snippet and specified headers.
    """
    if metadata_headers is None:
        metadata_headers = ['From', 'To', 'Cc', 'Subject', 'Date']
    credentials = await check_saved_access_token()
    if not credentials:
        logger.error("No valid credentials available.")
        return None
    service = build('gmail', 'v1', credentials=credentials)
    try:
        message = service.users().messages().get(userId='me', id=email_id, format='metadata', metadataHeaders=metadata_headers).execute()
        headers = message.get('payload', {}).get('headers', [])
        email_details = {header['name']: header['value'] for header in headers if header['name'] in metadata_headers}
        email_details['snippet'] = message.get('snippet', 'No snippet available')
        return email_details
    except Exception as e:
        logger.error(f"Failed to fetch email content: {e}")
        return None

import re
import base64
from email.message import EmailMessage
from googleapiclient.discovery import build
import logging

logger = logging.getLogger(__name__)

async def is_valid_email(email):
    """Simple regex check for validating an email address."""
    return re.match(r"[^@]+@[^@]+\.[^@]+", email) is not None

async def draft_email(to, subject, message_text):
    if not await is_valid_email(to):
        logger.error(f"Invalid email address: {to}")
        return {"status": "error", "message": "Invalid email address"}

    credentials = await check_saved_access_token()
    if not credentials:
        logger.error("No valid credentials available.")
        return {"status": "error", "message": "No valid credentials"}

    service = build('gmail', 'v1', credentials=credentials)
    email_message = EmailMessage()
    email_message.set_content(message_text)
    email_message['To'] = to
    email_message['From'] = 'me'
    email_message['Subject'] = subject
    encoded_message = base64.urlsafe_b64encode(email_message.as_bytes()).decode()
    draft_body = {'message': {'raw': encoded_message}}
    try:
        draft = service.users().drafts().create(userId='me', body=draft_body).execute()
        return {"status": "success", "draft_id": draft['id']}
    except Exception as e:
        logger.error(f"Failed to create draft: {e}")
        return {"status": "error", "message": str(e)}

async def send_email(draft_id):
    credentials = await check_saved_access_token()
    if not credentials:
        logger.error("No valid credentials available.")
        return {"status": "error", "message": "No valid credentials"}

    service = build('gmail', 'v1', credentials=credentials)
    try:
        sent_message = service.users().drafts().send(userId='me', body={'id': draft_id}).execute()
        return {"status": "success", "sent_message_id": sent_message['id']}
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return {"status": "error", "message": str(e)}

async def create_calendar_event(summary, location, start_time, end_time, attendees=None):
    credentials = await check_saved_access_token()
    if not credentials:
        logger.error("No valid credentials available for Google Calendar.")
        return None

    service = build('calendar', 'v3', credentials=credentials)

    event = {
        'summary': summary,
        'location': location,
        'start': {
            'dateTime': start_time,
            'timeZone': 'America/Los_Angeles',
        },
        'end': {
            'dateTime': end_time,
            'timeZone': 'America/Los_Angeles',
        },
        'attendees': [{'email': attendee} for attendee in attendees] if attendees else [],
    }

    try:
        created_event = service.events().insert(calendarId='primary', body=event).execute()
        logger.info(f"Event created: {created_event.get('htmlLink')}")
        return created_event
    except Exception as e:
        logger.error(f"Failed to create calendar event: {e}")
        return None
    
async def get_events_for_next_10_days():
    credentials = await check_saved_access_token()
    if not credentials:
        logger.error("No valid credentials available for Google Calendar.")
        return None

    service = build('calendar', 'v3', credentials=credentials)
    now = datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
    ten_days_later = (datetime.utcnow() + timedelta(days=10)).isoformat() + 'Z'

    try:
        events_result = service.events().list(calendarId='primary', timeMin=now, timeMax=ten_days_later,
                                              singleEvents=True, orderBy='startTime').execute()
        events = events_result.get('items', [])
        if not events:
            logger.info("No upcoming events found.")
            return []

        # Extracting details of each event
        events_details = []
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            summary = event.get('summary', 'No Title')
            location = event.get('location', 'No Location Specified')
            description = event.get('description', 'No Description')
            attendees = ', '.join([attendee['email'] for attendee in event.get('attendees', []) if 'email' in attendee])

            event_detail = {
                'summary': summary,
                'start': start,
                'end': end,
                'location': location,
                'description': description,
                'attendees': attendees
            }
            events_details.append(event_detail)

        return events_details
    except Exception as e:
        logger.error(f"Failed to fetch events: {e}")
        return None