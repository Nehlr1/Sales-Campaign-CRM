import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import smtplib
from email.mime.text import MIMEText
import dns.resolver
import re
import time
import schedule
from datetime import datetime
import queue
import threading
import logging
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account

# Setting up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    filename="crm_system.log"
)
logger = logging.getLogger(__name__)

class Gmail:
    def __init__(self, credentials):
        """Initializeing Gmail API service"""
        self.service = build("gmail", "v1", credentials=credentials)
    
    def get_unread_messages(self, query=""):
        """Fetching unread messages matching the query"""
        try:
            # Adding "is:unread" to the query
            full_query = f"is:unread {query}".strip()
            
            # Calling the Gmail API
            results = self.service.users().messages().list(
                userId="me",
                q=full_query
            ).execute()
            
            messages = results.get("messages", [])
            
            # Fetching full message details
            full_messages = []
            for message in messages:
                msg = self.service.users().messages().get(
                    userId="me",
                    id=message["id"]
                ).execute()
                full_messages.append(msg)
                
                # Marking message as read
                self.service.users().messages().modify(
                    userId="me",
                    id=message["id"],
                    body={"removeLabelIds": ["UNREAD"]}
                ).execute()
            
            return full_messages
            
        except Exception as e:
            logger.error(f"Error fetching Gmail messages: {str(e)}")
            return []

class TaskQueue:
    """Thread-safe task queue for managing lead processing"""
    def __init__(self):
        # Queuing for verification and outreach tasks
        self.verification_queue = queue.Queue()
        self.outreach_queue = queue.Queue()
        
    def add_verification_task(self, lead):
        # Adding lead to verification queue
        self.verification_queue.put(lead)
        
    def add_outreach_task(self, lead):
        # Adding lead to outreach queue
        self.outreach_queue.put(lead)
        
    def get_verification_task(self):
        # Getting next verification lead if available
        return self.verification_queue.get() if not self.verification_queue.empty() else None
        
    def get_outreach_task(self):
        # Getting next outreach lead if available
        return self.outreach_queue.get() if not self.outreach_queue.empty() else None

class EmailValidator:
    """Dedicated email validation class with extendable functionality"""
    def __init__(self):
        # Loading disposable email domains
        self.disposable_domains = self._load_disposable_domains()
        
    def _load_disposable_domains(self):
        # Setting of known disposable email domains
        return {"example.com", "mailinator.com", "tempmail.net", "company.com", "test.com", "business.com"}
    
    def _check_syntax(self, email):
        # Validateing email format using regex
        return re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", email)
    
    def _is_disposable(self, email):
        # Checking if the email domain is in the disposable list
        domain = email.split("@")[-1].lower()
        return domain in self.disposable_domains
    
    def _check_mx_records(self, email):
        # Verifying if the domain has MX records (valid mail server)
        domain = email.split("@")[-1]
        try:
            return bool(dns.resolver.resolve(domain, "MX"))
        except Exception:
            return False
        
    def validate(self, email):
        # Checking if email format is valid
        if not self._check_syntax(email):
            return False
        # Checking if email is from a disposable domain
        if self._is_disposable(email):
            return False
        # Verifying if the domain has MX records
        return self._check_mx_records(email)

class CRMHandler:
    """Handles interactions with a CRM system using Google Sheets and Gmail."""
    def __init__(self, creds_file, sheet_key, worksheet_name):
        self.setup_credentials(creds_file, sheet_key, worksheet_name)
        self.email_validator = EmailValidator()
        self.last_processed_row = 1
    
        
    def setup_credentials(self, creds_file, sheet_key, worksheet_name):
        # Authenticateing and setting up Google Sheets and Gmail API clients
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify"
        ]
        try:
            # Loading service account credentials
            creds = service_account.Credentials.from_service_account_file(
                creds_file,
                scopes=scope
            )
            
            # Initializeng Google Sheets client
            client = gspread.authorize(creds)
            self.sheet = client.open_by_key(sheet_key).worksheet(worksheet_name)
            
            # Initializing Gmail client
            self.gmail = Gmail(creds)
            
        except Exception as e:
            logger.error(f"Failed to setup credentials: {str(e)}")
            raise

    def get_leads(self):
        # Retrieveing all lead records from the sheet.
        return self.sheet.get_all_records()
    
    def get_new_leads(self):
        # Fetch new leads that haven't been processed.
        all_records = self.sheet.get_all_records()
        return [
            {"index": idx, "data": record} 
            for idx, record in enumerate(all_records) 
            if idx + 2 > self.last_processed_row and not record.get("Processing Status")
        ]

    def update_lead(self, row_index, updates):
        # Updateing lead record with new data
        headers = self.sheet.row_values(1) # Getting column headers
        cells = []
        for col, val in updates.items():
            try:
                col_index = headers.index(col) + 1 # Finding column index
                cells.append(gspread.Cell(
                    row=row_index + 2, # Adjusting for header row
                    col=col_index,
                    value=val
                ))
            except ValueError as e:
                logger.error(f"Column {col} not found in headers: {str(e)}")
        if cells:
            self.sheet.update_cells(cells)

    def validate_email(self, email):
        # Validate an email address using EmailValidator
        return self.email_validator.validate(email)

class AgentA(CRMHandler):
    """Agent responsible for processing lead verification tasks"""
    def __init__(self, creds_file, sheet_key, worksheet_name, task_queue):
        super().__init__(creds_file, sheet_key, worksheet_name)
        self.task_queue = task_queue
        self.running = False
        
    def start_processing(self):
        """Continuously fetch and process verification tasks."""
        self.running = True
        while self.running:
            lead = self.task_queue.get_verification_task() # Fetching a lead from the queue
            if lead:
                self.process_lead(lead) # Processing the lead
            time.sleep(1) # Preventing excessive CPU usage
                
    def process_lead(self, lead):
        """Validating and verifying a lead, updating the CRM accordingly."""
        try:
            self.update_lead(lead["index"], {"Processing Status": "Verifying"}) # Marking as verifying
            
            # Validating email and perform additional checks
            is_valid = self.validate_email(lead["data"]["Email"])
            additional_checks_passed = self.perform_additional_checks(lead["data"])
            
            verification_status = "Y" if (is_valid and additional_checks_passed) else "N"
            
            # Updating lead status
            updates = {
                "Email Verified (Y/N)": verification_status,
                "Processing Status": "Verified",
                "Verification Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            self.update_lead(lead["index"], updates)
            
            # If verified, adding the lead to the outreach queue
            if verification_status == "Y":
                self.task_queue.add_outreach_task(lead)
                
        except Exception as e:
            logger.error(f"Error processing lead {lead['data'].get('Email')}: {str(e)}")
            self.update_lead(lead["index"], {
                "Processing Status": "Error",
                "Notes": f"Verification failed: {str(e)}"
            })
    
    def perform_additional_checks(self, lead_data):
        """Performing additional verification checks on the lead."""
        checks = [
            self.check_industry(lead_data),
            self.check_company_size(lead_data),
            self.check_contact_details(lead_data)
        ]
        return all(checks) # Passes only if all checks return True
    
    def check_industry(self, lead_data):
        """Ensuring the lead is not from a competitor industry."""
        return lead_data.get("Industry", "").lower() not in ["competitor", "direct competitor"]
    
    def check_company_size(self, lead_data):
        """Rejecting leads from test or invalid companies."""
        return lead_data.get("Company", "").lower() != "test company"
    
    def check_contact_details(self, lead_data):
        """Ensuring all required contact fields are present."""
        required_fields = ["Email", "Company", "Contact Number"]
        return all(lead_data.get(field) for field in required_fields)

class AgentB(CRMHandler):
    """Agent responsible for processing outreach tasks, including email sending and retries."""
    def __init__(self, creds_file, sheet_key, worksheet_name, smtp_config, task_queue):
        super().__init__(creds_file, sheet_key, worksheet_name)
        self.smtp_config = smtp_config # SMTP configuration for sending emails
        self.task_queue = task_queue # Shared task queue for outreach tasks
        self.running = False # Controlling flag for processing loop
        self.retry_queue = queue.Queue() # Queuing for retrying failed email attempts
        
    def start_processing(self):
        """Continuously processing outreach tasks and retry failed emails."""
        self.running = True
        while self.running:
            self.process_retry_queue() # Handleing failed email attempts first
            lead = self.task_queue.get_outreach_task() # Fetching a lead for outreach
            if lead:
                self.process_lead(lead) # Processing the outreach
            time.sleep(1) # Preventing excessive CPU usage
                
    def process_retry_queue(self):
        """Retrying sending emails for leads that previously failed (up to 3 attempts)."""
        while not self.retry_queue.empty():
            lead, attempts = self.retry_queue.get()
            if attempts < 3:
                success = self.send_email(lead["data"]) # Attempting to send email again
                if not success:
                    self.retry_queue.put((lead, attempts + 1)) # Re-adding to queue with incremented attempt count
                    
    def process_lead(self, lead):
        """Sending outreach email and update CRM accordingly."""
        try:
            self.update_lead(lead["index"], {"Processing Status": "Outreach"}) # Marking as outreach in progress
            success = self.send_email(lead["data"]) # Sending the outreach email
            
            if not success:
                self.retry_queue.put((lead, 1)) # Adding to retry queue if sending fails
                return

            # Updating lead status after successful email    
            self.update_lead(lead["index"], {
                "Processing Status": "Completed",
                "Response Status": "Pending Response",
                "Outreach Date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
        except Exception as e:
            logger.error(f"Error in outreach to {lead['data'].get('Email')}: {str(e)}")
            self.update_lead(lead["index"], {
                "Processing Status": "Error",
                "Notes": f"Outreach failed: {str(e)}"
            })
    
    def send_email(self, lead):
        """Sending an email to the lead using SMTP."""
        msg = MIMEText("Your custom sales message here...") # Creating email body
        msg["Subject"] = "Special Offer for Your Business" # Email subject
        msg["From"] = self.smtp_config["email"] # Sender email
        msg["To"] = lead["Email"] # Recipient email
        
        try:
            # Establishing SMTP connection and send email
            with smtplib.SMTP(self.smtp_config["server"], self.smtp_config["port"]) as server:
                server.starttls() # Securing the connection
                server.login(self.smtp_config["email"], self.smtp_config["password"]) # Authentication
                server.send_message(msg) # Sending email
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {lead['Email']}: {str(e)}")
            return False

class Supervisor(CRMHandler):
    """Supervisor class responsible for monitoring leads, email tasks, and generating reports."""
    def __init__(self, creds_file, sheet_key, worksheet_name, task_queue):
        super().__init__(creds_file, sheet_key, worksheet_name)
        self.task_queue = task_queue # Shared task queue for assigning verification tasks
        self.running = False # Control flag for the monitoring process
        
    def start_monitoring(self):
        """Continuously monitoring new leads and email tasks at regular intervals."""
        self.running = True
        while self.running:
            self.monitor_new_leads() # Checking for new leads
            self.monitor_email_tasks() # Checking for new email tasks
            time.sleep(300) # Sleeping for 5 minutes before the next monitoring cycle
            
    def monitor_new_leads(self):
        """Fetches new leads and assigns them for verification."""
        try:
            new_leads = self.get_new_leads() # Retrieving newly added leads
            for lead in new_leads:
                self.task_queue.add_verification_task(lead) # Assigning lead to verification queue
                self.last_processed_row = lead["index"] + 2 # Updating the last processed row
        except Exception as e:
            logger.error(f"Error monitoring leads: {str(e)}")
            
    def monitor_email_tasks(self):
        """Checking for unread emails with campaign tasks and processes them."""
        try:
            messages = self.gmail.get_unread_messages(
                query="subject:New Campaign Task"
            ) # Fetching unread emails related to campaign tasks
            for msg in messages:
                self.process_email_task(msg) # Processing each email task
        except Exception as e:
            logger.error(f"Error monitoring emails: {str(e)}")
            
    def process_email_task(self, email_message):
        """Processes an incoming email task (to be implemented based on email format)."""
        pass # Placeholder for future implementation

    def generate_report(self):
        """Generating a summary report of lead verification and responses."""
        leads = self.get_leads() # Fetching all leads from the CRM
        report = {
            "total_leads": len(leads), # Total number of leads
            "verified": sum(1 for l in leads if l.get("Email Verified (Y/N)") == "Y"),
            "responses": {
                "Interested": 0,
                "Not Interested": 0,
                "No Response": 0
            }
        }
        # Categorizing responses from the lead data
        for lead in leads:
            status = lead.get("Response Status", "No Response")
            if status in report["responses"]:
                report["responses"][status] += 1
        
        return report # Returning the report as a dictionary

    def send_report(self, recipient, smtp_config):
        """Sending the generated campaign report via email."""
        report = self.generate_report() # Generating report data
        # Formatting the report into a readable email body
        body = f"""
        Sales Campaign Report:
        Total Leads: {report["total_leads"]}
        Verified Leads: {report["verified"]}
        Responses:
        - Interested: {report["responses"]["Interested"]}
        - Not Interested: {report["responses"]["Not Interested"]}
        - No Response: {report["responses"]["No Response"]}
        """
        
        # Constructing the email message
        msg = MIMEText(body.strip())
        msg["Subject"] = "Daily Campaign Report"
        msg["From"] = smtp_config["email"]
        msg["To"] = recipient
        
        try:
            # Establishing SMTP connection and send the report email
            with smtplib.SMTP(smtp_config["server"], smtp_config["port"]) as server:
                server.starttls() # Securing the connection
                server.login(smtp_config["email"], smtp_config["password"]) # Authentication
                server.send_message(msg) # Sending the email
        except Exception as e:
            logger.error(f"Failed to send report: {str(e)}") # Logging any email sending errors

def main():
    # Configuration: Loading credentials and settings from environment variables
    USER_EMAIL = os.getenv('USER_EMAIL') # Email for sending reports
    APP_PASSWORD = os.getenv('APP_PASSWORD') # Application-specific password for SMTP authentication
    manager_email = 'manager_email@gmail.com' # Email address to receive daily reports

    # Google Sheets credentials and sheet information
    GOOGLE_CREDS = "credentials.json" # Path to Google credentials file
    SHEET_KEY = "1nxDTg_k6zg06hhubwV711852hhnK4Xyu03nGxpsyJ0s" # Google Sheet key
    WORKSHEET = "SalesCampaignLeads" # Worksheet name containing sales campaign leads
    
    # SMTP configuration for sending emails
    SMTP_CONFIG = {
        "server": "smtp.gmail.com",
        "port": 587, # Standard SMTP port for Gmail
        "email": USER_EMAIL,
        "password": APP_PASSWORD
    }

    # Initializing components
    task_queue = TaskQueue()
    
    supervisor = Supervisor(GOOGLE_CREDS, SHEET_KEY, WORKSHEET, task_queue)
    agent_a = AgentA(GOOGLE_CREDS, SHEET_KEY, WORKSHEET, task_queue)
    agent_b = AgentB(GOOGLE_CREDS, SHEET_KEY, WORKSHEET, SMTP_CONFIG, task_queue)
    
    # Starting processing threads
    threads = [
        threading.Thread(target=supervisor.start_monitoring),
        threading.Thread(target=agent_a.start_processing),
        threading.Thread(target=agent_b.start_processing)
    ]
    
    for thread in threads:
        thread.start()
        
    # Scheduling regular reports
    schedule.every().day.at("16:00").do(
        supervisor.send_report,
        manager_email,
        SMTP_CONFIG
    )
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)
    except KeyboardInterrupt:
        # Graceful shutdown on user interruption (Ctrl+C)
        supervisor.running = False
        agent_a.running = False
        agent_b.running = False
        
        for thread in threads:
            thread.join()

if __name__ == "__main__":
    main() # Executing the main function when the script is run