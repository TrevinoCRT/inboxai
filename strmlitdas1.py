# Import necessary libraries
import openai
import dash
from dash import html, dcc, Input, Output, State, callback, dash_table
import dash_bootstrap_components as dbc
import asyncio
from assistants import process_thread_with_assistant, add_files_to_existing_vector_store  # Importing the chat function and upload function from assistants.py
from driveapi import check_saved_access_token, start_oauth_and_server, download_drive_file  # Importing the download function from driveapi.py
from loguru import logger
import os
from dash_google_picker import GooglePicker
import base64
import subprocess
import json
import gmailapi
import requests
import threading
from dash.dependencies import Input, Output, State, MATCH, ALL, ALLSMALLER
import pandas as pd  # Import pandas for handling dataframes

# Load client secrets for OAuth for Gmail
with open('client_secret.json') as f:
    client_secrets_gmail = json.load(f)
client_id_gmail = client_secrets_gmail['installed']['client_id']
client_secret_gmail = client_secrets_gmail['installed']['client_secret']

# Load client secrets for OAuth for Google Drive Picker
with open('client_secret_drive.json') as f:
    client_secrets_drive = json.load(f)
client_id_drive = client_secrets_drive['web']['client_id']
developer_key_drive = client_secrets_drive['web']['client_secret']  # Assuming developer key is the client secret for simplicity

# Set your OpenAI Assistant ID here
assistant_id = "asst_9Ktnx0WWDOswzeL1FvDqOWRF"

# Initialize the OpenAI client with hardcoded API key from .env file
openai.api_key = os.getenv("OPENAI_API_KEY")
client = openai

# Initialize the Dash app
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

# Define the layout
app.layout = html.Div([
    dbc.Row([
        dbc.Col([
            html.H3("File Upload and Processing"),
            dcc.Upload(
                id='upload-file',
                children=html.Div(["Drag and Drop or ", html.A("Select Files")]),
                style={
                    'width': '100%', 'height': '60px', 'lineHeight': '60px',
                    'borderWidth': '1px', 'borderStyle': 'dashed', 'borderRadius': '5px',
                    'textAlign': 'center', 'margin': '10px'
                },
                multiple=True,
                accept=".xlsx,.pptx,.doc,.docx,.txt,.pdf,.csv"
            ),
            dbc.Button('Process Files', id='process-files-btn', className='btn btn-primary mt-2'),
            html.Div(id='output-process-files'),
            dbc.Button('Open Google Picker', id='open-picker-button', n_clicks=0, className='btn btn-secondary mt-2'),
            GooglePicker(
                id='google-picker',
                client_id=client_id_drive,
                developer_key='AIzaSyDZR9iSFvLBi8PV-y2djYPeMYlOLUzOdzE'
            ),
            html.Div(id='display-documents', style={'whiteSpace': 'pre-wrap'}),
            html.Div(id='display-action')
        ], width=3),
        dbc.Col([
            html.H3("Chat Interface"),
            dcc.Store(id='chat-store'),
            html.Div([
                dcc.Markdown('#### Chat History', style={'color': 'black'}),
                html.Div(id='chat-messages', style={
                    'height': '400px', 'overflow': 'auto', 'border': '1px solid #ccc',
                    'margin': '10px', 'padding': '10px', 'borderRadius': '5px'
                }),
                dcc.Input(id='chat-input', type='text', placeholder='Enter your message', style={'width': '70%'}),
                dbc.Button('Send', id='send-btn', className='btn btn-success mt-2'),
            ], style={'backgroundColor': '#f8f9fa', 'padding': '20px', 'borderRadius': '5px', 'boxShadow': '2px 2px 10px #aaa'}),
        ], width=9)
    ]),
    dbc.Row([
        dbc.Col([
            html.H3("Email Dashboard"),
            dash_table.DataTable(
                id='email-table',
                columns=[
                    {"name": "ID", "id": "id"},  # Add the 'ID' column
                    {"name": "From", "id": "From"},
                    {"name": "To", "id": "To"},
                    {"name": "Subject", "id": "Subject"},
                    {"name": "Date", "id": "Date"},
                    {"name": "Snippet", "id": "Snippet"}
                ],
                data=[],  # Placeholder data
                style_table={'height': '300px', 'overflowY': 'auto'}
            ),
            dbc.Button("Refresh Emails", id="refresh-emails-btn", className="btn btn-info mt-2"),
            html.Div(id='email-content-display', style={'whiteSpace': 'pre-wrap'})
        ], width=12)
    ])
])

# Callback to fetch and display emails in a structured table
# Callback to fetch and display emails in a structured table
@app.callback(
    Output('email-table', 'data'),
    Input('refresh-emails-btn', 'n_clicks'),
    prevent_initial_call=True
)
def update_email_table(n_clicks):
    logger.debug("Refreshing emails...")
    token = asyncio.run(gmailapi.check_saved_access_token())
    if not token:
        logger.info("No valid access token. Initiating OAuth flow.")
        asyncio.run(gmailapi.start_oauth_and_server())
        token = asyncio.run(gmailapi.check_saved_access_token())
        if not token:
            logger.error("Failed to obtain valid access token after OAuth flow.")
            return []

    emails = asyncio.run(gmailapi.fetch_relevant_emails(max_results=15, include_snippets=True))
    logger.debug(f"Emails fetched: {emails}")

    # Transform the data to match the DataTable column IDs and include 'id' column
    transformed_emails = []
    for email in emails:
        transformed_email = {
            'id': email.get('id'),  # Include the email ID
            'From': email.get('from'),
            'To': email.get('to', 'N/A'),  # Assuming 'to' might be missing and defaulting to 'N/A'
            'Subject': email.get('subject'),
            'Date': email.get('date', 'N/A'),  # Assuming 'date' might be missing and defaulting to 'N/A'
            'Snippet': email.get('snippet')
        }
        transformed_emails.append(transformed_email)

    df_emails = pd.DataFrame(transformed_emails)
    logger.debug(f"DataFrame created: {df_emails}")

    data_dict = df_emails.to_dict('records')
    logger.debug(f"Data dict for DataTable: {data_dict}")
    return data_dict
# Callback to display the content of a selected email
@app.callback(
    Output('email-content-display', 'children'),
    Input('email-table', 'active_cell'),
    State('email-table', 'data'),
    prevent_initial_call=True
)
def display_email_content(active_cell, data):
    if active_cell:
        email_id = data[active_cell['row']]['id']
        email_content = asyncio.run(gmailapi.fetch_custom_email_content(email_id, metadata_headers=['From', 'To', 'Cc', 'Subject', 'Date']))
        formatted_content = f"From: {email_content['From']}\nTo: {email_content['To']}\nCc: {email_content.get('Cc', 'N/A')}\nSubject: {email_content['Subject']}\nDate: {email_content['Date']}\n\n{email_content['snippet']}"
        return formatted_content
# Callbacks for chat interface
@callback(
    Output('chat-messages', 'children'),
    Input('send-btn', 'n_clicks'),
    State('chat-input', 'value'),
    State('chat-store', 'data'),
    prevent_initial_call=True
)
def update_chat(n_clicks, message, chat_history):
    if n_clicks is None:
        return  # Do nothing if no clicks
    if chat_history is None:
        chat_history = []

    async def process_message():
        response = await process_thread_with_assistant(message, assistant_id)
        response_text = response.get('text', ["No response from assistant."])[0]
        chat_history.append({'role': 'user', 'content': f"You: {message}", 'style': {'color': 'blue', 'fontWeight': 'bold'}})
        chat_history.append({'role': 'assistant', 'content': dcc.Markdown(f"Assistant: {response_text}")})
        return [html.Div([html.Div(msg['content'], style=msg.get('style', {})) for msg in chat_history], style={'margin': '5px'})]

    if dash.callback_context.triggered[0]['prop_id'].startswith('send-btn'):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(process_message())
            return result
        finally:
            loop.close()

# Helper function to manage the event loop for running asynchronous tasks
def run_async_tasks(task, *args, **kwargs):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = None
    try:
        result = loop.run_until_complete(task(*args, **kwargs))
    finally:
        loop.close()
    return result

# Callbacks for file processing
@callback(
    Output('output-process-files', 'children'),
    [Input('process-files-btn', 'n_clicks'), Input('google-picker', 'documents')],
    [State('upload-file', 'contents')],
    prevent_initial_call=True
)
def process_files(n_clicks, documents, contents):
    if not documents and not contents:
        return "No files uploaded or selected."
    file_paths = []
    if documents:
        for doc in documents:
            file_id = doc['id']
            file_name = doc['name']
            # Run download_drive_file in a separate thread to avoid blocking
            file_path = run_async_tasks(download_drive_file, file_id, file_name)
            if file_path:
                file_paths.append(file_path)
            else:
                return f"Failed to download {file_name}"
    if contents:
        for content in contents:
            data = content.split(",")[1]
            with open("temp_file", "wb") as f:
                f.write(base64.b64decode(data))
            file_paths.append("temp_file")
    vector_store_id = "vs_7HNjrhDESus71F1VeUVHsVgB"
    # Run add_files_to_existing_vector_store in a separate thread to avoid blocking
    result = run_async_tasks(add_files_to_existing_vector_store, file_paths, vector_store_id)
    return result

# Callbacks for Google Picker
@callback(
    Output('google-picker', 'open'),
    [Input('open-picker-button', 'n_clicks')],
    [State('google-picker', 'open')]
)
def open_google_picker(n_clicks, is_open):
    if n_clicks > 0:
        return not is_open
    return False

@callback(
    Output('display-documents', 'children'),
    [Input('google-picker', 'documents')],
    prevent_initial_call=True
)
def display_output(documents):
    docs = [f"{doc['name']} ({doc['id']})" for doc in documents]
    return "\n".join(docs)

@callback(
    Output('display-action', 'children'),
    [Input('google-picker', 'action')],
    prevent_initial_call=True
)
def display_action(action):
    if action == "loaded":
        return "Opened the Google Picker Popup"
    elif action == "picked":
        return "Picked a document"
    elif action == "cancelled":
        return "Cancelled the Google Picker Popup"
    return f'Action: {action}'

# Run the server
if __name__ == '__main__':
    app.run_server(debug=True)
