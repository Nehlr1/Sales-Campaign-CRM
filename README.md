# Description
This project is a Sales Campaign CRM system that integrates with Google Sheets and Gmail APIs to manage and automate lead verification and outreach tasks. The system fetches leads from a Google Sheet, validates their email addresses, and sends outreach emails. It also monitors new leads and email tasks, and generates daily reports.

## Getting Started

Clone this repository and install the requirements:

```sh
git clone https://github.com/Nehlr1/Sales-Campaign-CRM.git
cd Sales-Campaign-CRM
py -m pip install --user virtualenv
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## Creating Credentials
You must set up a project in the Google Cloud Console and activate the Google Sheets and Google Gmail API before you can build the `credentials.json` file for the API. Take these actions:

### Step 1: Create a Project in Google Cloud Console

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Click on the project dropdown at the top of the page, then click on "New Project."
3. Enter a name "Sales CRM" for your project and click "Create."

### Step 2: Enable the Google Sheets API

1. In the Cloud Console, click on beside Google Cloud logo using the left sidebar.
2. Click on `APIs & Services` and select `Enabled APIs & Services`.
3. Click on `+ Enabled APIs & Services`.
4. Search for `Google Sheets API` and `Gmail API` in the search bar.
5. Select `Google Sheets API` and `Gmail API` from the results.
6. Click the "Enable" button.

### Step 3: Create Service Account Credentials

1. In the Cloud Console, navigate to APIs & Services > `Credentials` using the left sidebar.
2. Click on the `+ Create Credentials` dropdown and select `Service account`
3. Under `Service account,` create a new service account like ` Sheet and Gmail API`. and press `CREATE AND CONTINIUE`
4. For `Role,` choose `Owner` to give the service account access to your entire project.
5. Once the Service account is created, using the left sidebar, click on the `Manage service accounts` and you will see the created service account. 
6. Click on the action button and select `manage keys`
7. Click the `ADD KEY` button choosing the `Create new key` and choose `JSON`. This will download a JSON file containing your credentials.

### Step 4: Save and Use Your Credentials

In the directory containing your Python script, save the downloaded JSON file as `credentials.json`. This file is what your Python script will use to authenticate itself.

Since your `credentials.json` file includes important information, make sure you keep it private and don't share it with the public.

## Running the Application

1. Ensure you have set the following environment variables:
   - `USER_EMAIL`: Your email address for sending reports.
   - `APP_PASSWORD`: Your application-specific password for SMTP authentication.

2. Run the application:
```sh
python sales_campaign_crm.py
```

## Components

### Gmail
Handles interactions with the Gmail API to fetch unread messages and mark them as read.

### TaskQueue
Manages a thread-safe queue for lead verification and outreach tasks.

### EmailValidator
Validates email addresses by checking their syntax, domain, and MX records.

### CRMHandler
Handles interactions with the Google Sheets API to fetch, update, and validate leads.

### AgentA
Processes lead verification tasks by validating email addresses and performing additional checks.

### AgentB
Processes outreach tasks by sending emails and retrying failed attempts.

### Supervisor
Monitors new leads and email tasks, generates reports, and sends them via email.

## Scheduling Reports
The application schedules daily reports to be sent at 16:00. You can modify the schedule in the `main` function of `sales_campaign_crm.py`.

## Logging
Logs are stored in `crm_system.log` for monitoring errors and activities.