# Project Overview

This project is a comprehensive application that integrates various functionalities such as email fetching, file processing, Google Drive interaction, and chat interface using OpenAI's API. The application is built using Python and Dash, and it leverages several third-party libraries and APIs to provide a seamless user experience.

## Table of Contents

- [Project Overview](#project-overview)
- [Installation](#installation)
- [Usage](#usage)
- [Features](#features)
- [File Structure](#file-structure)
- [Contributing](#contributing)
- [License](#license)

## Installation

### Prerequisites

- Python 3.7 or higher
- Pip (Python package installer)
- Google Cloud account with appropriate API credentials
- OpenAI API key

### Steps

1. **Clone the repository:**
    ```sh
    git clone https://github.com/your-repo/your-project.git
    cd your-project
    ```

2. **Install the required packages:**
    ```sh
    pip install -r requirements.txt
    ```

3. **Set up environment variables:**
    Create a `.env` file in the root directory and add your OpenAI API key and other necessary environment variables.
    ```env
    OPENAI_API_KEY=your_openai_api_key
    ```

4. **Set up Google Cloud credentials:**
    Download your Google Cloud service account JSON file and set the `GOOGLE_APPLICATION_CREDENTIALS` environment variable.
    ```sh
    export GOOGLE_APPLICATION_CREDENTIALS="path/to/your/service-account-file.json"
    ```

## Usage

1. **Run the application:**
    ```sh
    python strmlitdas1.py
    ```

2. **Access the application:**
    Open your web browser and go to `http://127.0.0.1:8050/`.

## Features

- **Email Dashboard:**
  - Fetch and display unread emails.
  - View email content.
  - Draft and send emails.

- **File Processing:**
  - Upload files from local storage.
  - Select files from Google Drive using Google Picker.
  - Process and add files to an existing vector store.

- **Chat Interface:**
  - Interact with an OpenAI assistant.
  - Maintain chat history.

## File Structure
